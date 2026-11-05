import ipaddress
import os
import select
import socket
import struct
import threading
import time
from typing import Callable, Optional, Set, Tuple
from alan_dpi.engine.models import BypassVector, VECTOR_REGISTRY
from alan_dpi.engine.mutator import TlsByteMutator


BENIGN_WIN_SOCKET_ERRORS = {10004, 10035, 10038, 10053, 10054}


class FullDuplexMutatorBridge:
    SOCKET_BUFFER_SIZE = 4 * 1024 * 1024
    STREAM_CHUNK_SIZE = 65536
    UPLINK_SHIELD_WINDOW_BYTES = 16384
    CONNECT_TIMEOUT_SEC = 6.0
    HANDSHAKE_READ_TIMEOUT_SEC = 6.5

    def __init__(
        self,
        listen_port: int = 20809,
        log_fn: Optional[Callable[[str], None]] = None,
        on_endpoint_change: Optional[Callable[[str], None]] = None,
    ):
        self.listen_port = int(listen_port)
        self.remote_host: str = ""
        self.remote_port: int = 443
        self.active_vector: BypassVector = VECTOR_REGISTRY[0]
        self.custom_stride: int = 400
        self.jitter_bytes: int = 20
        self.raw_passthrough: bool = False
        self.tun_bind_enabled: bool = False

        self.running: bool = False
        self.server_sock: Optional[socket.socket] = None
        self.tx_bytes_total: int = 0
        self.rx_bytes_total: int = 0
        self.total_sessions_handled: int = 0

        self._physical_bind_ip: str = ""
        self._lock = threading.RLock()
        self._stats_lock = threading.Lock()
        self._live_sockets: Set[socket.socket] = set()
        self._log_fn = log_fn
        self._on_endpoint_change = on_endpoint_change

    def _log(self, msg: str):
        if self._log_fn is not None:
            try:
                self._log_fn(msg)
            except Exception:
                pass

    def _add_tx(self, n: int):
        if n > 0:
            with self._stats_lock:
                self.tx_bytes_total += int(n)

    def _add_rx(self, n: int):
        if n > 0:
            with self._stats_lock:
                self.rx_bytes_total += int(n)

    def reset_counters(self):
        with self._stats_lock:
            self.tx_bytes_total = 0
            self.rx_bytes_total = 0

    def refresh_physical_interface(self, enable_tun_bind: bool = False):
        with self._lock:
            self.tun_bind_enabled = bool(enable_tun_bind)
            if not enable_tun_bind:
                self._physical_bind_ip = ""
                return

        detected_ip = ""
        for probe_target in (("1.1.1.1", 80), ("8.8.8.8", 53)):
            probe_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe_sock.settimeout(1.0)
                probe_sock.connect(probe_target)
                cand_ip = probe_sock.getsockname()[0]
                if cand_ip and (not cand_ip.startswith("198.18.")) and (not cand_ip.startswith("127.")):
                    detected_ip = cand_ip
                    break
            except Exception:
                continue
            finally:
                try:
                    probe_sock.close()
                except Exception:
                    pass

        with self._lock:
            self._physical_bind_ip = detected_ip

    def _apply_tun_bypass_bind_if_needed(self, sock: socket.socket, target_host: str):
        if (os.name != "nt") or target_host.startswith("127.") or (":" in target_host):
            return
        with self._lock:
            should_bind = self.tun_bind_enabled
            bind_ip = self._physical_bind_ip
        if should_bind and bind_ip:
            try:
                sock.bind((bind_ip, 0))
            except Exception:
                pass

    @property
    def active_session_count(self) -> int:
        with self._lock:
            return len(self._live_sockets) // 2

    def update_route(
        self,
        remote_host: str,
        remote_port: int,
        vector: BypassVector,
        custom_stride: int = 400,
        jitter_bytes: int = 20,
        raw_passthrough: bool = False,
        flush_existing_pool: bool = False,
    ):
        clean_host = (remote_host or "").strip().strip("[]")
        direct_vec = vector.family == "DIRECT"
        effective_passthrough = bool(raw_passthrough) or direct_vec

        with self._lock:
            self.remote_host = clean_host
            self.remote_port = int(remote_port)
            self.active_vector = vector
            self.custom_stride = int(custom_stride)
            self.jitter_bytes = int(jitter_bytes)
            self.raw_passthrough = effective_passthrough

        if (self._on_endpoint_change is not None) and bool(clean_host):
            try:
                self._on_endpoint_change(clean_host)
            except Exception:
                pass

        if flush_existing_pool:
            self.drop_active_connections()

        mode_label = "DIRECT-PASSTHROUGH" if effective_passthrough else f"{vector.vector_id} ({vector.code_name})"
        self._log(f"[Bridge] Route -> {clean_host}:{remote_port} | {mode_label}")

    def drop_active_connections(self):
        with self._lock:
            current_socks = list(self._live_sockets)
            self._live_sockets.clear()
        for s in current_socks:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass

    def start(self):
        with self._lock:
            if self.running and (self.server_sock is not None):
                return
            self.running = True
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", self.listen_port))
            srv.listen(256)
            self.server_sock = srv

        self._log(f"[Bridge] Online at 127.0.0.1:{self.listen_port}")
        threading.Thread(target=self._accept_loop, name=f"AlanBridge-{self.listen_port}", daemon=True).start()

    def stop(self):
        with self._lock:
            self.running = False
            srv = self.server_sock
            self.server_sock = None
        if srv is not None:
            try:
                srv.close()
            except Exception:
                pass
        self.drop_active_connections()

    def _accept_loop(self):
        while True:
            with self._lock:
                if (not self.running) or (self.server_sock is None):
                    break
                srv = self.server_sock
            try:
                client_sock, _ = srv.accept()
                with self._lock:
                    self.total_sessions_handled += 1
                    sid = self.total_sessions_handled % 10000
                threading.Thread(
                    target=self._handle_session,
                    args=(client_sock, sid),
                    daemon=True,
                ).start()
            except OSError:
                if not self.running:
                    break
                time.sleep(0.02)
            except Exception:
                if not self.running:
                    break

    @staticmethod
    def _configure_high_perf_socket(sock: socket.socket):
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, FullDuplexMutatorBridge.SOCKET_BUFFER_SIZE)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, FullDuplexMutatorBridge.SOCKET_BUFFER_SIZE)
        except Exception:
            pass
        if hasattr(socket, "SIO_KEEPALIVE_VALS"):
            try:
                sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 15000, 3000))
            except Exception:
                pass

    @staticmethod
    def _open_remote_socket(host: str, port: int, bind_helper: Callable[[socket.socket, str], None], timeout: float) -> socket.socket:
        family = socket.AF_INET
        target_addr = host
        try:
            ip_obj = ipaddress.ip_address(host)
            if ip_obj.version == 6:
                family = socket.AF_INET6
        except ValueError:
            infos = socket.getaddrinfo(host, int(port), socket.AF_UNSPEC, socket.SOCK_STREAM)
            if infos:
                family = infos[0][0]
                target_addr = str(infos[0][4][0])

        remote_sock = socket.socket(family, socket.SOCK_STREAM)
        FullDuplexMutatorBridge._configure_high_perf_socket(remote_sock)
        if family == socket.AF_INET:
            bind_helper(remote_sock, target_addr)
        remote_sock.settimeout(timeout)
        remote_sock.connect((target_addr, int(port)))
        return remote_sock

    @staticmethod
    def _read_exact_initial_flight(sock: socket.socket, timeout: float = 6.5) -> Tuple[bytes, bytes]:
        sock.settimeout(timeout)
        hdr = bytearray()
        while len(hdr) < 5:
            chunk = sock.recv(5 - len(hdr))
            if not chunk:
                return bytes(hdr), b""
            hdr.extend(chunk)

        if hdr[0] != 0x16:
            sock.settimeout(0.045)
            try:
                rest = sock.recv(16384)
                return bytes(hdr) + rest, b""
            except Exception:
                return bytes(hdr), b""

        rec_len = struct.unpack("!H", hdr[3:5])[0]
        if (rec_len <= 0) or (rec_len > 16384):
            sock.settimeout(0.045)
            try:
                rest = sock.recv(16384)
                return bytes(hdr) + rest, b""
            except Exception:
                return bytes(hdr), b""

        body = bytearray()
        while len(body) < rec_len:
            chunk = sock.recv(min(16384, rec_len - len(body)))
            if not chunk:
                break
            body.extend(chunk)

        return bytes(hdr) + bytes(body), b""

    def _register_pair(self, c_sock: socket.socket, r_sock: Optional[socket.socket]):
        with self._lock:
            self._live_sockets.add(c_sock)
            if r_sock is not None:
                self._live_sockets.add(r_sock)

    def _unregister_pair(self, c_sock: socket.socket, r_sock: Optional[socket.socket]):
        with self._lock:
            self._live_sockets.discard(c_sock)
            if r_sock is not None:
                self._live_sockets.discard(r_sock)

    def _handle_session(self, client_sock: socket.socket, sid: int):
        with self._lock:
            r_host = self.remote_host
            r_port = self.remote_port
            vec = self.active_vector
            stride = self.custom_stride
            jitter = self.jitter_bytes
            passthrough = self.raw_passthrough

        if not r_host:
            try:
                client_sock.close()
            except Exception:
                pass
            return

        remote_sock: Optional[socket.socket] = None
        self._register_pair(client_sock, None)

        try:
            self._configure_high_perf_socket(client_sock)

            t0 = time.perf_counter()
            remote_sock = self._open_remote_socket(
                host=r_host,
                port=r_port,
                bind_helper=self._apply_tun_bypass_bind_if_needed,
                timeout=self.CONNECT_TIMEOUT_SEC,
            )
            tcp_ms = max(1, int((time.perf_counter() - t0) * 1000))
            self._register_pair(client_sock, remote_sock)

            trailing_initial = b""
            if not passthrough:
                first_data, trailing_initial = self._read_exact_initial_flight(
                    client_sock,
                    timeout=self.HANDSHAKE_READ_TIMEOUT_SEC,
                )
                if not first_data:
                    return

                is_tls_hello = (len(first_data) >= 44) and (first_data[0] == 0x16) and (first_data[5] == 0x01)
                is_http_req = first_data.startswith((b"GET ", b"POST ", b"HEAD ", b"PUT ", b"OPTIONS ", b"DELETE "))

                if is_tls_hello:
                    sent, wire_trace = TlsByteMutator.transmit_client_hello(
                        sock=remote_sock,
                        ch_record=first_data,
                        vector=vec,
                        custom_stride=stride,
                        jitter_bytes=jitter,
                    )
                    self._log(f"[S#{sid:04d}] TCP={tcp_ms}ms | {vec.vector_id}: {wire_trace}")
                elif is_http_req:
                    sent, wire_trace = TlsByteMutator.transmit_plain_http(
                        sock=remote_sock,
                        http_payload=first_data,
                        vector=vec,
                        custom_stride=stride,
                        jitter_bytes=jitter,
                    )
                    self._log(f"[S#{sid:04d}] TCP={tcp_ms}ms | {vec.vector_id}: {wire_trace}")
                else:
                    remote_sock.sendall(first_data)
                    sent = len(first_data)
                self._add_tx(sent)

            remote_sock.settimeout(None)
            client_sock.settimeout(None)

            def _downlink_pump():
                try:
                    while self.running:
                        data = remote_sock.recv(self.STREAM_CHUNK_SIZE)
                        if not data:
                            break
                        client_sock.sendall(data)
                        self._add_rx(len(data))
                except Exception:
                    pass
                finally:
                    try:
                        client_sock.shutdown(socket.SHUT_WR)
                    except Exception:
                        pass

            def _uplink_pump():
                flight_num = 0 if passthrough else 1
                uplink_app_bytes = 0
                oob_shield_done = False
                pending_seed = trailing_initial

                try:
                    while self.running:
                        if pending_seed:
                            data = pending_seed
                            pending_seed = b""
                        else:
                            data = client_sock.recv(self.STREAM_CHUNK_SIZE)
                            if not data:
                                break

                        flight_num += 1

                        if (not passthrough) and (flight_num == 2) and vec.coalesce_flight2 and (len(data) <= 180):
                            try:
                                if client_sock.fileno() >= 0:
                                    r_ready, _, _ = select.select([client_sock], [], [], 0.018)
                                    if r_ready:
                                        extra = client_sock.recv(self.STREAM_CHUNK_SIZE)
                                        if extra:
                                            data = data + extra
                            except Exception:
                                pass

                        is_multi_frag = (
                            (not passthrough)
                            and (vec.family == "FRAGMENT")
                            and (vec.frag_flights > 1)
                            and (flight_num <= vec.frag_flights)
                            and (vec.frag_slice_max > 0)
                        )

                        use_shield = (
                            (not passthrough)
                            and ((vec.uplink_oob_shield and (not oob_shield_done)) or (vec.uplink_mss_clamp > 0))
                            and (uplink_app_bytes < self.UPLINK_SHIELD_WINDOW_BYTES)
                        )

                        if is_multi_frag:
                            sent_frag = TlsByteMutator.transmit_fragmented_buffer(
                                sock=remote_sock,
                                payload=data,
                                min_len=vec.frag_slice_min,
                                max_len=vec.frag_slice_max,
                                min_delay_ms=vec.frag_delay_min_ms,
                                max_delay_ms=vec.frag_delay_max_ms,
                            )
                            self._add_tx(sent_frag)
                            uplink_app_bytes += len(data)
                        elif use_shield:
                            want_oob = bool(vec.uplink_oob_shield) and (not oob_shield_done) and (data[0] == 0x17)
                            if want_oob:
                                oob_shield_done = True
                            sent_sh = TlsByteMutator.transmit_uplink_shield_frame(
                                sock=remote_sock,
                                payload=data,
                                inject_oob=want_oob,
                                mss_clamp=vec.uplink_mss_clamp,
                            )
                            self._add_tx(sent_sh)
                            uplink_app_bytes += len(data)
                        else:
                            remote_sock.sendall(data)
                            self._add_tx(len(data))
                            uplink_app_bytes += len(data)
                except Exception:
                    pass
                finally:
                    try:
                        remote_sock.shutdown(socket.SHUT_WR)
                    except Exception:
                        pass

            down_thread = threading.Thread(target=_downlink_pump, daemon=True)
            down_thread.start()
            _uplink_pump()
            down_thread.join(timeout=18.0)

        except OSError as os_err:
            win_code = getattr(os_err, "winerror", 0)
            if win_code not in BENIGN_WIN_SOCKET_ERRORS:
                self._log(f"[S#{sid:04d}] Closed: {os_err}")
        except Exception as exc:
            self._log(f"[S#{sid:04d}] Closed: {exc}")
        finally:
            self._unregister_pair(client_sock, remote_sock)
            try:
                client_sock.close()
            except Exception:
                pass
            if remote_sock is not None:
                try:
                    remote_sock.close()
                except Exception:
                    pass