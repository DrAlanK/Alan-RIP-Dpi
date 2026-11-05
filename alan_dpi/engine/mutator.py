import os
import random
import socket
import struct
import time
from typing import Dict, List, Tuple
from alan_dpi.engine.models import BypassVector


_POLY_OOB_POOL = (
    b"\x21\x23\x24\x25\x26\x2a\x2b\x2d\x2e\x33\x3b\x3d\x3f"
    b"\x40\x42\x47\x4b\x4e\x51\x57\x5a\x5e\x61\x6d\x71\x78\x7a\x7e"
)


class TlsByteMutator:
    @staticmethod
    def _poly_oob_byte() -> bytes:
        idx = random.randint(0, len(_POLY_OOB_POOL) - 1)
        return _POLY_OOB_POOL[idx : idx + 1]

    @staticmethod
    def _poly_record_version(base_ver: int) -> int:
        if base_ver == 0x0304:
            return random.choice((0x0301, 0x0303, 0x0304))
        return random.choice((0x0301, 0x0303))

    @staticmethod
    def inspect_client_hello(record: bytes) -> Dict[str, int]:
        rec_len = len(record)
        mid_guess = max(14, min(180, rec_len // 3))
        info = {
            "is_valid_ch": 0,
            "record_len": rec_len,
            "cipher_suites_pos": 43,
            "cipher_suites_len": 32,
            "ext_total_len_pos": max(48, min(120, mid_guess - 12)),
            "sni_ext_pos": mid_guess,
            "sni_list_len_pos": mid_guess + 4,
            "sni_name_len_pos": mid_guess + 7,
            "sni_name_pos": mid_guess + 9,
            "sni_name_len": 20,
            "sni_first_dot_pos": mid_guess + 15,
            "sni_last_dot_pos": mid_guess + 21,
            "alpn_ext_pos": -1,
            "sup_ver_ext_pos": -1,
            "key_share_ext_pos": -1,
        }
        if (rec_len < 48) or (record[0] != 0x16) or (record[5] != 0x01):
            return info

        try:
            pos = 43
            if pos >= rec_len:
                return info
            sid_len = record[pos]
            pos += 1 + sid_len
            if (pos + 2) > rec_len:
                return info

            info["cipher_suites_pos"] = pos
            ciph_len = struct.unpack("!H", record[pos : pos + 2])[0]
            info["cipher_suites_len"] = ciph_len
            pos += 2 + ciph_len
            if (pos + 1) > rec_len:
                return info

            comp_len = record[pos]
            pos += 1 + comp_len
            if (pos + 2) > rec_len:
                return info

            info["ext_total_len_pos"] = pos
            ext_total_len = struct.unpack("!H", record[pos : pos + 2])[0]
            pos += 2
            end = min(rec_len, pos + ext_total_len)
            info["is_valid_ch"] = 1

            while (pos + 4) <= end:
                etype = struct.unpack("!H", record[pos : pos + 2])[0]
                elen = struct.unpack("!H", record[pos + 2 : pos + 4])[0]
                ext_body_end = pos + 4 + elen
                if ext_body_end > end:
                    break

                if (etype == 0x0000) and ((pos + 9) <= ext_body_end):
                    name_len = struct.unpack("!H", record[pos + 7 : pos + 9])[0]
                    name_start = pos + 9
                    name_end = min(ext_body_end, name_start + name_len)
                    info["sni_ext_pos"] = pos
                    info["sni_list_len_pos"] = pos + 4
                    info["sni_name_len_pos"] = pos + 7
                    info["sni_name_pos"] = name_start
                    info["sni_name_len"] = max(1, name_end - name_start)

                    host_bytes = record[name_start:name_end]
                    first_dot = host_bytes.find(b".")
                    last_dot = host_bytes.rfind(b".")
                    if first_dot > 0:
                        info["sni_first_dot_pos"] = name_start + first_dot
                    else:
                        info["sni_first_dot_pos"] = name_start + max(1, info["sni_name_len"] // 2)
                    if last_dot > 0:
                        info["sni_last_dot_pos"] = name_start + last_dot
                    else:
                        info["sni_last_dot_pos"] = info["sni_first_dot_pos"]
                elif etype == 0x0010:
                    info["alpn_ext_pos"] = pos
                elif etype == 0x002B:
                    info["sup_ver_ext_pos"] = pos
                elif etype == 0x0033:
                    info["key_share_ext_pos"] = pos

                pos = ext_body_end
        except Exception:
            pass
        return info

    @staticmethod
    def locate_sni_offsets(record: bytes) -> Dict[str, int]:
        return TlsByteMutator.inspect_client_hello(record)

    @staticmethod
    def rewrite_outer_version(record: bytes, version: int) -> bytes:
        if (len(record) < 5) or (record[0] != 0x16):
            return record
        ba = bytearray(record)
        ba[1] = (version >> 8) & 0xFF
        ba[2] = version & 0xFF
        return bytes(ba)

    @staticmethod
    def build_preamble_bytes(preamble_mode: str) -> bytes:
        if preamble_mode == "zero0304":
            ver = random.choice(("0301", "0303", "0304"))
            return bytes.fromhex(f"16{ver}0000")
        if preamble_mode == "2xzero":
            return bytes.fromhex("16030100001603040000")
        if preamble_mode == "4xzero":
            return bytes.fromhex("1603010000160302000016030300001603040000")
        return b""

    @staticmethod
    def split_record_atomic(record: bytes, cut_offset: int, version: int) -> bytes:
        if (len(record) < 10) or (cut_offset <= 5) or (cut_offset >= len(record)):
            return TlsByteMutator.rewrite_outer_version(record, version)
        hs = record[5:]
        cut_rel = cut_offset - 5
        part1 = hs[:cut_rel]
        part2 = hs[cut_rel:]
        return (
            struct.pack("!BHH", 0x16, 0x0301, len(part1))
            + part1
            + struct.pack("!BHH", 0x16, version, len(part2))
            + part2
        )

    @staticmethod
    def reframe_handshake_chunks(
        hs_body: bytes,
        chunk_sizes: List[int],
        version: int,
        alternating_versions: Tuple[int, ...] = (),
    ) -> List[bytes]:
        frames: List[bytes] = []
        cursor = 0
        total = len(hs_body)
        idx = 0
        for sz in chunk_sizes:
            if cursor >= total:
                break
            take = min(max(1, int(sz)), total - cursor)
            seg = hs_body[cursor : cursor + take]
            rec_ver = alternating_versions[idx % len(alternating_versions)] if alternating_versions else version
            frames.append(struct.pack("!BHH", 0x16, rec_ver, len(seg)) + seg)
            cursor += take
            idx += 1
        if cursor < total:
            rem = hs_body[cursor:]
            rec_ver = alternating_versions[idx % len(alternating_versions)] if alternating_versions else version
            frames.append(struct.pack("!BHH", 0x16, rec_ver, len(rem)) + rem)
        return frames

    @staticmethod
    def _safe_send_urgent(sock: socket.socket, chunk: bytes, urgent_byte: bytes = b"") -> int:
        if not chunk:
            return 0
        decoy = urgent_byte[:1] if urgent_byte else TlsByteMutator._poly_oob_byte()
        try:
            combined = chunk + decoy
            sent = sock.send(combined, socket.MSG_OOB)
            if sent < len(combined):
                rem = combined[sent:-1] if (sent < len(chunk)) else b""
                if rem:
                    sock.sendall(rem)
            return len(combined)
        except OSError:
            sock.sendall(chunk)
            return len(chunk)

    @staticmethod
    def transmit_uplink_shield_frame(
        sock: socket.socket,
        payload: bytes,
        inject_oob: bool = False,
        mss_clamp: int = 0,
    ) -> int:
        if not payload:
            return 0

        total_sent = 0
        view = payload

        if inject_oob and (len(view) > 20) and (view[0] == 0x17) and (view[1] == 0x03):
            total_sent += TlsByteMutator._safe_send_urgent(sock, view[:3])
            view = view[3:]

        if (mss_clamp > 0) and (len(view) > mss_clamp):
            jit_mss = max(512, mss_clamp + random.randint(-24, 24))
            cursor = 0
            limit = len(view)
            while cursor < limit:
                piece = view[cursor : cursor + jit_mss]
                sock.sendall(piece)
                total_sent += len(piece)
                cursor += len(piece)
        elif view:
            sock.sendall(view)
            total_sent += len(view)

        return total_sent

    @staticmethod
    def transmit_fragmented_buffer(
        sock: socket.socket,
        payload: bytes,
        min_len: int,
        max_len: int,
        min_delay_ms: int,
        max_delay_ms: int,
    ) -> int:
        if not payload:
            return 0
        cursor = 0
        total_len = len(payload)
        lo = max(1, int(min_len))
        hi = max(lo, int(max_len))
        while cursor < total_len:
            step = random.randint(lo, hi)
            chunk = payload[cursor : cursor + step]
            sock.sendall(chunk)
            cursor += len(chunk)
            if (cursor < total_len) and (max_delay_ms > 0):
                delay_s = random.uniform(min_delay_ms, max_delay_ms) / 1000.0
                if delay_s > 0:
                    time.sleep(delay_s)
        return total_len

    @staticmethod
    def _transmit_tail_segments(
        sock: socket.socket,
        tail_buf: bytes,
        forward_cuts: List[int],
        jitter_bytes: int = 20,
        second_urgent_delta: int = 0,
    ) -> int:
        if not tail_buf:
            return 0

        tail_len = len(tail_buf)
        if second_urgent_delta > 0:
            jitter = random.randint(-jitter_bytes, jitter_bytes) if (jitter_bytes > 0) else 0
            target_delta = max(24, second_urgent_delta + jitter)
            cut_pos = target_delta if (target_delta < tail_len) else max(1, (tail_len * 2) // 3)
            if 0 < cut_pos < tail_len:
                sent_u = TlsByteMutator._safe_send_urgent(sock, tail_buf[:cut_pos])
                time.sleep(0.001)
                sock.sendall(tail_buf[cut_pos:])
                return sent_u + (tail_len - cut_pos)

        if not forward_cuts:
            sock.sendall(tail_buf)
            return tail_len

        resolved_cuts: List[int] = []
        for base_delta in forward_cuts:
            use_jitter = (base_delta > 60) and (jitter_bytes > 0)
            jitter = random.randint(-jitter_bytes, jitter_bytes) if use_jitter else 0
            cut_candidate = max(20, base_delta + jitter)
            if 0 < cut_candidate < tail_len:
                resolved_cuts.append(cut_candidate)
            elif 0 < base_delta < tail_len:
                resolved_cuts.append(base_delta)
            elif tail_len > 48:
                resolved_cuts.append((tail_len * 7) // 10)

        points = sorted(set([0] + resolved_cuts + [tail_len]))
        sent_bytes = 0
        for idx in range(len(points) - 1):
            segment = tail_buf[points[idx] : points[idx + 1]]
            if segment:
                sock.sendall(segment)
                sent_bytes += len(segment)
                if (len(points) > 2) and (idx < (len(points) - 2)):
                    time.sleep(0.002)
        return sent_bytes

    @staticmethod
    def _transmit_sni_dot_fibonacci(
        sock: socket.socket,
        hs_body: bytes,
        offsets: Dict[str, int],
        jitter_bytes: int = 20,
    ) -> Tuple[int, str]:
        body_len = len(hs_body)
        sni_start_rel = max(6, offsets["sni_name_pos"] - 5)
        dot_rel = max(sni_start_rel + 1, offsets["sni_first_dot_pos"] - 5)
        fib_steps = [1, 2, 3, 5, 8]

        dot_anchor = max(4, dot_rel - 3)
        chunk_plan: List[int] = []

        if dot_anchor > (sni_start_rel + 2):
            first_cut = sni_start_rel + 2
            bridge_cut = dot_anchor - first_cut
            chunk_plan.append(first_cut)
            chunk_plan.append(bridge_cut)
        else:
            chunk_plan.append(dot_anchor)

        chunk_plan.extend(fib_steps)

        frames = TlsByteMutator.reframe_handshake_chunks(
            hs_body=hs_body,
            chunk_sizes=chunk_plan,
            version=0x0303,
            alternating_versions=(0x0301, 0x0303, 0x0303, 0x0301, 0x0303, 0x0303, 0x0301, 0x0303),
        )

        dot_frame_idx = 4 if (dot_anchor > (sni_start_rel + 2)) else 3
        dot_frame_idx = min(len(frames) - 1, dot_frame_idx)

        flight_a = b"".join(frames[:dot_frame_idx])
        flight_b = b"".join(frames[dot_frame_idx:])

        sock.sendall(flight_a)
        jit = random.randint(-jitter_bytes, jitter_bytes) if (jitter_bytes > 0) else 0
        tail_stride = max(64, 340 + jit)
        if len(flight_b) > (tail_stride + 24):
            sock.sendall(flight_b[:tail_stride])
            sock.sendall(flight_b[tail_stride:])
        elif flight_b:
            sock.sendall(flight_b)

        total_len = len(flight_a) + len(flight_b)
        return total_len, f"Coalesced-Sync({len(frames)}F) | {total_len}B"

    @staticmethod
    def _transmit_hybrid_vector(
        sock: socket.socket,
        hs_body: bytes,
        offsets: Dict[str, int],
        vector: BypassVector,
        custom_stride: int = 400,
        jitter_bytes: int = 20,
    ) -> Tuple[int, str]:
        body_len = len(hs_body)
        sni_ext_rel = max(6, offsets["sni_ext_pos"] - 5)
        sni_name_rel = max(10, offsets["sni_name_pos"] - 5)
        sni_len = max(4, offsets["sni_name_len"])

        if vector.hybrid_mode == "phantom_seam_oob":
            c1 = max(38, sni_ext_rel - 4) if (sni_ext_rel > 44) else max(8, sni_ext_rel - 2)
            c1 = min(body_len - 16, c1)
            part1 = hs_body[:c1]
            part2 = hs_body[c1:]

            rec1 = struct.pack("!BHH", 0x16, 0x0301, len(part1)) + part1
            rec2 = struct.pack("!BHH", 0x16, 0x0304, len(part2)) + part2
            combined = rec1 + rec2

            target_host_byte = min(len(combined) - 4, sni_name_rel + 10 + min(3, max(1, sni_len // 3)))
            sent_head = TlsByteMutator._safe_send_urgent(sock, combined[:target_host_byte])

            stride_val = int(custom_stride) if (custom_stride > 0) else 400
            sent_tail = TlsByteMutator._transmit_tail_segments(
                sock=sock,
                tail_buf=combined[target_host_byte:],
                forward_cuts=[stride_val],
                jitter_bytes=jitter_bytes,
            )
            total = sent_head + sent_tail
            return total, f"Core-Omega | {total}B"

        if vector.hybrid_mode == "sni_microcell_pincer":
            cell_start = max(8, min(body_len - 16, sni_name_rel + min(3, max(1, sni_len // 4))))
            cell_len = min(5, max(2, min(sni_len // 2, body_len - cell_start - 6)))
            cell_end = cell_start + cell_len

            p1 = hs_body[:cell_start]
            p2 = hs_body[cell_start:cell_end]
            p3 = hs_body[cell_end:]

            rec1 = struct.pack("!BHH", 0x16, 0x0304, len(p1)) + p1
            rec2 = struct.pack("!BHH", 0x16, 0x0301, len(p2)) + p2
            rec3 = struct.pack("!BHH", 0x16, 0x0304, len(p3)) + p3

            oob1_cut = min(len(rec1) - 2, max(10, offsets["sni_ext_pos"] + 1))
            sent_1 = TlsByteMutator._safe_send_urgent(sock, rec1[:oob1_cut])

            rem_stream = rec1[oob1_cut:] + rec2 + rec3
            jit = random.randint(-jitter_bytes, jitter_bytes) if (jitter_bytes > 0) else 0
            pincer_stride = max(48, 360 + jit)

            if len(rem_stream) > (pincer_stride + 24):
                sent_2 = TlsByteMutator._safe_send_urgent(sock, rem_stream[:pincer_stride])
                time.sleep(0.0015)
                sock.sendall(rem_stream[pincer_stride:])
                total = sent_1 + sent_2 + (len(rem_stream) - pincer_stride)
            else:
                sock.sendall(rem_stream)
                total = sent_1 + len(rem_stream)
            return total, f"Core-Window | {total}B"

        k1 = min(sni_ext_rel - 2, 41) if (sni_ext_rel > 45) else max(8, sni_ext_rel // 2)
        k2 = min(body_len - 20, max(k1 + 4, sni_name_rel + 2))
        k3 = min(body_len - 14, k2 + max(3, min(6, sni_len // 3)))
        k4 = min(body_len - 8, k3 + max(3, min(6, sni_len // 3)))

        sizes = [k1, k2 - k1, k3 - k2, k4 - k3]
        frames = TlsByteMutator.reframe_handshake_chunks(
            hs_body=hs_body,
            chunk_sizes=sizes,
            version=0x0303,
            alternating_versions=(0x0301, 0x0303, 0x0301, 0x0303, 0x0303),
        )
        burst_1 = b"".join(frames[:3])
        burst_2 = b"".join(frames[3:])
        sock.sendall(burst_1)

        jit = random.randint(-jitter_bytes, jitter_bytes) if (jitter_bytes > 0) else 0
        stride_380 = max(40, 380 + jit)
        if len(burst_2) > (stride_380 + 20):
            sock.sendall(burst_2[:stride_380])
            time.sleep(0.0015)
            sock.sendall(burst_2[stride_380:])
        elif burst_2:
            sock.sendall(burst_2)

        total = len(burst_1) + len(burst_2)
        return total, f"Record-Sync | {total}B"

    @staticmethod
    def transmit_plain_http(
        sock: socket.socket,
        http_payload: bytes,
        vector: BypassVector,
        custom_stride: int = 400,
        jitter_bytes: int = 20,
    ) -> Tuple[int, str]:
        if (vector.family == "DIRECT") or (len(http_payload) < 16):
            sock.sendall(http_payload)
            return len(http_payload), f"HTTP-Direct | {len(http_payload)}B"

        if (vector.family == "FRAGMENT") and (vector.frag_slice_max > 0):
            sent = TlsByteMutator.transmit_fragmented_buffer(
                sock=sock,
                payload=http_payload,
                min_len=vector.frag_slice_min,
                max_len=vector.frag_slice_max,
                min_delay_ms=vector.frag_delay_min_ms,
                max_delay_ms=vector.frag_delay_max_ms,
            )
            return sent, f"HTTP-Frag({vector.frag_slice_min}-{vector.frag_slice_max}B)"

        lower_buf = http_payload.lower()
        host_idx = lower_buf.find(b"\r\nhost:")
        if (host_idx != -1) and ((host_idx + 10) < len(http_payload)):
            val_start = host_idx + 7
            while (val_start < len(http_payload)) and (http_payload[val_start : val_start + 1] in (b" ", b"\t")):
                val_start += 1
            cut = min(len(http_payload) - 2, val_start + 3)
            uses_oob = (vector.urgent_mode != "none") or (vector.hybrid_mode in ("phantom_seam_oob", "sni_microcell_pincer"))
            if (cut > 0) and uses_oob:
                sent_u = TlsByteMutator._safe_send_urgent(sock, http_payload[:cut])
                rem = TlsByteMutator._transmit_tail_segments(
                    sock=sock,
                    tail_buf=http_payload[cut:],
                    forward_cuts=[custom_stride] if (custom_stride > 0) else [400],
                    jitter_bytes=jitter_bytes,
                )
                return sent_u + rem, f"HTTP-HostDesync | {sent_u + rem}B"
            if cut > 0:
                sock.sendall(http_payload[:cut])
                time.sleep(0.0015)
                sock.sendall(http_payload[cut:])
                return len(http_payload), f"HTTP-HostSplit | {len(http_payload)}B"

        sock.sendall(http_payload)
        return len(http_payload), f"HTTP-Direct | {len(http_payload)}B"

    @staticmethod
    def transmit_client_hello(
        sock: socket.socket,
        ch_record: bytes,
        vector: BypassVector,
        custom_stride: int = 400,
        jitter_bytes: int = 20,
    ) -> Tuple[int, str]:
        if (vector.family == "DIRECT") or (len(ch_record) < 16):
            sock.sendall(ch_record)
            return len(ch_record), f"TLS-Direct | {len(ch_record)}B"

        ver = TlsByteMutator._poly_record_version(vector.outer_version)
        offsets = TlsByteMutator.inspect_client_hello(ch_record)
        hs_body = ch_record[5:]

        if (vector.hybrid_mode != "none") and (len(hs_body) >= 48):
            return TlsByteMutator._transmit_hybrid_vector(
                sock=sock,
                hs_body=hs_body,
                offsets=offsets,
                vector=vector,
                custom_stride=custom_stride,
                jitter_bytes=jitter_bytes,
            )

        if vector.record_envelope == "fibonacci_7rec":
            return TlsByteMutator._transmit_sni_dot_fibonacci(
                sock=sock,
                hs_body=hs_body,
                offsets=offsets,
                jitter_bytes=jitter_bytes,
            )

        if vector.record_envelope == "sni_dot_3rec":
            sni_start_rel = max(2, offsets["sni_name_pos"] - 5)
            dot_rel = max(sni_start_rel + 2, offsets["sni_first_dot_pos"] - 5)
            c1 = max(4, min(len(hs_body) - 8, dot_rel))
            mid_span = 3
            frames = TlsByteMutator.reframe_handshake_chunks(
                hs_body=hs_body,
                chunk_sizes=[c1, mid_span, max(1, len(hs_body) - c1 - mid_span)],
                version=0x0303,
                alternating_versions=(0x0301, 0x0303, 0x0303),
            )
            packed = b"".join(frames)
            sock.sendall(packed)
            return len(packed), f"Aligned-Relay | {len(packed)}B"

        if vector.record_envelope == "sni_mid_2rec":
            sni_start_rel = max(2, offsets["sni_name_pos"] - 5)
            sni_len = max(4, offsets["sni_name_len"])
            cut_rel = max(4, min(len(hs_body) - 4, sni_start_rel + (sni_len // 2)))
            frames = TlsByteMutator.reframe_handshake_chunks(
                hs_body=hs_body,
                chunk_sizes=[cut_rel],
                version=0x0303,
                alternating_versions=(0x0301, 0x0303),
            )
            packed = b"".join(frames)
            sock.sendall(packed)
            return len(packed), f"Stream-Balance | {len(packed)}B"

        mut_ch = TlsByteMutator.rewrite_outer_version(ch_record, ver)
        prefix = TlsByteMutator.build_preamble_bytes(vector.preamble)

        if (vector.urgent_mode == "cipher_pivot") and (len(mut_ch) > 96):
            full_buf = prefix + mut_ch
            pivot_cut = min(len(full_buf) - 48, len(prefix) + max(44, offsets["cipher_suites_pos"] + 1))
            anchor = int(vector.tail_anchor_bytes) if (vector.tail_anchor_bytes > 0) else 36
            anchor_jit = max(24, anchor + random.randint(-8, 8))
            tail_start = max(pivot_cut + 8, len(full_buf) - anchor_jit)
            sent_1 = TlsByteMutator._safe_send_urgent(sock, full_buf[:pivot_cut])
            sock.sendall(full_buf[pivot_cut:tail_start])
            sock.sendall(full_buf[tail_start:])
            total_sent = sent_1 + (len(full_buf) - pivot_cut)
            return total_sent, f"Core-Delta | {total_sent}B"

        if (vector.family == "FRAGMENT") and (vector.frag_slice_max > 0):
            full_frag_buf = prefix + mut_ch
            sent = TlsByteMutator.transmit_fragmented_buffer(
                sock=sock,
                payload=full_frag_buf,
                min_len=vector.frag_slice_min,
                max_len=vector.frag_slice_max,
                min_delay_ms=vector.frag_delay_min_ms,
                max_delay_ms=vector.frag_delay_max_ms,
            )
            return sent, f"Frag({vector.frag_slice_min}-{vector.frag_slice_max}B) | {sent}B"

        cuts = list(vector.forward_cuts)
        if (custom_stride > 0) and (len(cuts) == 1) and (cuts[0] == 400):
            cuts = [int(custom_stride)]

        sec_urg = vector.second_urgent_delta
        if (custom_stride > 0) and (sec_urg > 0):
            sec_urg = int(custom_stride)

        if vector.split_mode == "1pkt_midsni":
            cut = offsets["sni_name_pos"] + max(3, min(5, offsets["sni_name_len"] // 2))
            split_payload = prefix + TlsByteMutator.split_record_atomic(ch_record, cut, ver)
            sent = TlsByteMutator._transmit_tail_segments(
                sock=sock,
                tail_buf=split_payload,
                forward_cuts=cuts,
                jitter_bytes=jitter_bytes,
                second_urgent_delta=sec_urg,
            )
            return sent, f"AtomicSplit | {sent}B"

        full_buf = prefix + mut_ch
        shift = len(prefix)

        if vector.urgent_mode == "sni_tag":
            cut = min(len(full_buf) - 2, shift + offsets["sni_ext_pos"] + 1)
            if cut > 0:
                s_u = TlsByteMutator._safe_send_urgent(sock, full_buf[:cut])
                rem = TlsByteMutator._transmit_tail_segments(
                    sock=sock,
                    tail_buf=full_buf[cut:],
                    forward_cuts=cuts,
                    jitter_bytes=jitter_bytes,
                    second_urgent_delta=sec_urg,
                )
                return s_u + rem, f"Core-Alpha | {s_u + rem}B"

        if vector.urgent_mode == "mid_host":
            cut = min(
                len(full_buf) - 2,
                shift + offsets["sni_name_pos"] + max(3, min(5, offsets["sni_name_len"] // 2)),
            )
            if cut > 0:
                s_u = TlsByteMutator._safe_send_urgent(sock, full_buf[:cut])
                rem = TlsByteMutator._transmit_tail_segments(
                    sock=sock,
                    tail_buf=full_buf[cut:],
                    forward_cuts=cuts,
                    jitter_bytes=jitter_bytes,
                    second_urgent_delta=sec_urg,
                )
                return s_u + rem, f"Core-Sigma | {s_u + rem}B"

        if vector.urgent_mode == "sni_len":
            cut = min(len(full_buf) - 2, shift + offsets["sni_list_len_pos"] + 1)
            if cut > 0:
                s_u = TlsByteMutator._safe_send_urgent(sock, full_buf[:cut])
                rem = TlsByteMutator._transmit_tail_segments(
                    sock=sock,
                    tail_buf=full_buf[cut:],
                    forward_cuts=cuts,
                    jitter_bytes=jitter_bytes,
                    second_urgent_delta=sec_urg,
                )
                return s_u + rem, f"Core-Len | {s_u + rem}B"

        if vector.urgent_mode == "name_len":
            cut = min(len(full_buf) - 2, shift + offsets["sni_name_len_pos"] + 1)
            if cut > 0:
                s_u = TlsByteMutator._safe_send_urgent(sock, full_buf[:cut])
                rem = TlsByteMutator._transmit_tail_segments(
                    sock=sock,
                    tail_buf=full_buf[cut:],
                    forward_cuts=cuts,
                    jitter_bytes=jitter_bytes,
                    second_urgent_delta=sec_urg,
                )
                return s_u + rem, f"Core-NameLen | {s_u + rem}B"

        if vector.urgent_mode == "dual":
            c1 = shift + offsets["sni_ext_pos"] + 1
            c2 = min(len(full_buf) - 2, shift + offsets["sni_name_pos"] + 4)
            if 0 < c1 < c2:
                u1 = TlsByteMutator._safe_send_urgent(sock, full_buf[:c1])
                u2 = TlsByteMutator._safe_send_urgent(sock, full_buf[c1:c2])
                rem = TlsByteMutator._transmit_tail_segments(
                    sock=sock,
                    tail_buf=full_buf[c2:],
                    forward_cuts=cuts,
                    jitter_bytes=jitter_bytes,
                    second_urgent_delta=sec_urg,
                )
                return u1 + u2 + rem, f"Core-Dual | {u1 + u2 + rem}B"

        if vector.urgent_mode == "triple":
            c0 = shift + offsets["ext_total_len_pos"] + 1
            c1 = shift + offsets["sni_ext_pos"] + 1
            c2 = min(len(full_buf) - 2, shift + offsets["sni_name_pos"] + 4)
            if 0 < c0 < c1 < c2:
                u0 = TlsByteMutator._safe_send_urgent(sock, full_buf[:c0])
                u1 = TlsByteMutator._safe_send_urgent(sock, full_buf[c0:c1])
                u2 = TlsByteMutator._safe_send_urgent(sock, full_buf[c1:c2])
                rem = TlsByteMutator._transmit_tail_segments(
                    sock=sock,
                    tail_buf=full_buf[c2:],
                    forward_cuts=cuts,
                    jitter_bytes=jitter_bytes,
                    second_urgent_delta=sec_urg,
                )
                return u0 + u1 + u2 + rem, f"Core-Tri | {u0 + u1 + u2 + rem}B"

        sent = TlsByteMutator._transmit_tail_segments(
            sock=sock,
            tail_buf=full_buf,
            forward_cuts=cuts,
            jitter_bytes=jitter_bytes,
            second_urgent_delta=sec_urg,
        )
        return sent, f"Coalesced | {sent}B"