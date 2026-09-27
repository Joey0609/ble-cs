"""Example CS channel index selection following Core 6.1 Vol 6 Part H §4.1-4.2.

The algorithm structure (cr1 shuffling, CSA #3a/#3b/#3c, regeneration and
cycle closure) follows the specification, but every random draw comes from a
seeded Python PRNG standing in for the CS DRBG. Actual hop sequences depend on
the CS DRBG state, which is derived from the security setup and advances every
procedure, so they cannot be predicted offline. Uses only the standard library.
"""

import random

# CS channel k is centered at 2402 + k MHz. Channels around the advertising
# channels (0-1, 23-25, 77-78) are never used for CS.
ALLOWED_CHANNELS = (*range(2, 23), *range(26, 77))
ALLOWED_MASK = sum(1 << ch for ch in ALLOWED_CHANNELS)
HAT, X_PATTERN = 0, 1
# CSChannelJump: (seq1StartCh, seq2StartCh, maxRepsAllowed, saltRate), Table 4.2.
CSA3C_PARAMS = {2: (1, 76, 1, 2), 3: (77, 0, 1, 2), 4: (78, 0, 2, 2), 5: (78, 0, 2, 2),
                6: (76, 1, 3, 2), 7: (74, 1, 3, 2), 8: (76, 0, 3, 2)}
CS3C_N_INITIAL_SALT = 9
CS3C_N_FINAL_SALT = 4
LAST_INDEX = 78


def enabled_channels(channel_map: bytes) -> tuple[int, ...]:
    """Channel indices set in the map, including any reserved bits."""
    bits = int.from_bytes(channel_map, "little")
    return tuple(ch for ch in range(bits.bit_length()) if bits >> ch & 1)


def channel_map_bytes(channels) -> bytes:
    return sum(1 << ch for ch in set(channels)).to_bytes(10, "little")


def cr1(rng: random.Random, channels) -> list[int]:
    """Channel index shuffling function, §4.1.2 (inside-out shuffle)."""
    shuffled = [0] * len(channels)
    for i, channel in enumerate(channels):
        j = rng.randint(0, i)
        if i != j:
            shuffled[i] = shuffled[j]
        shuffled[j] = channel
    return shuffled


def _ramp(start, inc):
    """(k, channel) for start + k*inc: skip leading out-of-range values, stop on leaving the range."""
    values = []
    for k in range(LAST_INDEX + 2):
        channel = start + k * inc
        if 0 <= channel <= LAST_INDEX:
            values.append((k, channel))
        elif values:
            break
    return values


def shape_sequence(shape, jump, iteration, start_jitter) -> list[int]:
    """GenShapeSequence, §4.1.4.2.2."""
    seq1, seq2, _, _ = CSA3C_PARAMS[jump]
    offset = (iteration + start_jitter) % jump
    s1, s2 = seq1 + offset, seq2 + offset
    if shape == X_PATTERN:
        inc = jump if seq1 < seq2 else -jump
        # Interleave by computation index, s1 first; a finished ramp lets the other continue.
        merged = sorted(_ramp(s1, inc) + _ramp(s2, -inc), key=lambda item: item[0])
        return [channel for _, channel in merged]
    rising, falling = (s1, s2) if s1 < s2 else (s2, s1)
    return [ch for _, ch in _ramp(rising, jump)] + [ch for _, ch in _ramp(falling, -jump)]


def salt_sequences(rng, shape, shape_channels):
    """GenSalt, §4.1.4.2.3: returns (FirstAndEndSaltChSeq, MiddleSaltChSeq)."""
    used = set(shape_channels)
    quadrants = (range(0, 20), range(20, 40), range(40, 60), range(60, LAST_INDEX + 1))
    every = [list(q) for q in quadrants]
    unused = [[ch for ch in q if ch not in used] for q in quadrants]
    first_end, middle = ((1, 2), (0, 3)) if shape == X_PATTERN else ((2, 3), (0, 1))
    first_end_all = cr1(rng, every[first_end[0]] + every[first_end[1]])
    middle_all = cr1(rng, every[middle[0]] + every[middle[1]])
    first_end_unused = cr1(rng, unused[first_end[0]] + unused[first_end[1]])
    middle_unused = cr1(rng, unused[middle[0]] + unused[middle[1]])
    return first_end_unused + first_end_all, middle_unused + middle_all


def salted_sequence(rng, shape, jump, shape_channels, first, last) -> list[int]:
    """SaltChannelInsertion, §4.1.4.2.4."""
    first_end, middle = (iter(seq) for seq in salt_sequences(rng, shape, shape_channels))
    result, counts = [], [0, 0]

    def salt(from_first_end):
        channel = next(first_end if from_first_end else middle, None)
        if channel is not None:
            result.append(channel)
            counts[0 if from_first_end else 1] += 1

    if first:
        for n in range(rng.randrange(CS3C_N_INITIAL_SALT + 1)):
            salt(n % 2 == 0)
    salt_rate = CSA3C_PARAMS[jump][3]
    edge_quadrants = (1, 4) if shape == X_PATTERN else (1, 2)
    for i, channel in enumerate(shape_channels):
        if i % salt_rate == 0:
            salt(channel // 20 + 1 in edge_quadrants)
        result.append(channel)
    if last:
        for n in range(rng.randrange(CS3C_N_FINAL_SALT + 1)):
            salt(n % 2 == 0)
        deficit = counts[0] - counts[1]
        for _ in range(abs(deficit)):
            salt(deficit < 0)
    return result


def block_shuffle(rng, channels) -> list[int]:
    """FilterAndShuffle block shuffling, §4.1.4.2.5 (input already filtered)."""
    size = max(10, len(channels) // 4)
    blocks = max(1, len(channels) // size)
    result = []
    for i in range(blocks):
        end = (i + 1) * size if i < blocks - 1 else len(channels)
        result += cr1(rng, channels[i * size:end])
    return result


class ChannelSequencer:
    """Per-procedure channel index arrays, consumed in order and regenerated when exhausted (§4.1).

    Mode-0 uses CSA #3a with no limit. Non-mode-0 uses #3b or #3c for at most
    channel_map_repetition generations; after that the procedure closes (§4.2).
    """
    def __init__(self, configuration, seed):
        c = configuration
        self.rng = random.Random(seed)
        self.enabled = [ch for ch in enabled_channels(c.channel_map) if ch in ALLOWED_CHANNELS]
        self.algorithm = c.channel_selection_type
        self.shape, self.jump = c.ch3c_shape, c.ch3c_jump
        self.repetitions = c.channel_map_repetition
        self.cycles = 0
        self.start_jitter = 0
        self.mode0 = []
        self.non_mode0 = []

    def mode0_channel(self):
        if not self.mode0:
            self.mode0 = cr1(self.rng, self.enabled)
        return self.mode0.pop(0)

    def peek_non_mode0(self):
        """Next non-mode-0 channel without consuming it, or None once all cycles are used."""
        if not self.non_mode0:
            if self.cycles >= self.repetitions:
                return None
            self.non_mode0 = self._generate()
            self.cycles += 1
        return self.non_mode0[0]

    def take_non_mode0(self):
        channel = self.peek_non_mode0()
        self.non_mode0.pop(0)
        return channel

    def _generate(self):
        if self.algorithm == 0:
            return cr1(self.rng, self.enabled)
        if self.cycles == 0:
            self.start_jitter = self.rng.randrange(self.jump)
        shape = shape_sequence(self.shape, self.jump, self.cycles, self.start_jitter)
        salted = salted_sequence(self.rng, self.shape, self.jump, shape,
                                 first=self.cycles == 0, last=self.cycles == self.repetitions - 1)
        allowed = set(self.enabled)
        return block_shuffle(self.rng, [ch for ch in salted if ch in allowed])
