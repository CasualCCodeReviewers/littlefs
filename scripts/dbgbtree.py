#!/usr/bin/env python3

import bisect
import collections as co
import itertools as it
import math as m
import os
import struct


TAG_UNR         = 0x1000
TAG_SUPERMAGIC  = 0x0003
TAG_SUPERCONFIG = 0x0004
TAG_MROOT       = 0x0304
TAG_NAME        = 0x0100
TAG_BRANCH      = 0x0100
TAG_REG         = 0x0101
TAG_DIR         = 0x0102
TAG_STRUCT      = 0x0300
TAG_INLINED     = 0x0300
TAG_BLOCK       = 0x0302
TAG_BTREE       = 0x0303
TAG_MDIR        = 0x0305
TAG_UATTR       = 0x0400
TAG_ALT         = 0x4000
TAG_CRC         = 0x2000
TAG_FCRC        = 0x2100


# parse some rbyd addr encodings
# 0xa     -> [0xa]
# 0xa.b   -> ([0xa], b)
# 0x{a,b} -> [0xa, 0xb]
def rbydaddr(s):
    s = s.strip()
    b = 10
    if s.startswith('0x') or s.startswith('0X'):
        s = s[2:]
        b = 16
    elif s.startswith('0o') or s.startswith('0O'):
        s = s[2:]
        b = 8
    elif s.startswith('0b') or s.startswith('0B'):
        s = s[2:]
        b = 2

    trunk = None
    if '.' in s:
        s, s_ = s.split('.', 1)
        trunk = int(s_, b)

    if s.startswith('{') and '}' in s:
        ss = s[1:s.find('}')].split(',')
    else:
        ss = [s]

    addr = []
    for s in ss:
        if trunk is not None:
            addr.append((int(s, b), trunk))
        else:
            addr.append(int(s, b))

    return addr

def crc32c(data, crc=0):
    crc ^= 0xffffffff
    for b in data:
        crc ^= b
        for j in range(8):
            crc = (crc >> 1) ^ ((crc & 1) * 0x82f63b78)
    return 0xffffffff ^ crc

def fromle32(data):
    return struct.unpack('<I', data[0:4].ljust(4, b'\0'))[0]

def fromleb128(data):
    word = 0
    for i, b in enumerate(data):
        word |= ((b & 0x7f) << 7*i)
        word &= 0xffffffff
        if not b & 0x80:
            return word, i+1
    return word, len(data)

def fromtag(data):
    tag = (data[0] << 8) | data[1]
    weight, d = fromleb128(data[2:])
    size, d_ = fromleb128(data[2+d:])
    return tag>>15, tag&0x7fff, weight, size, 2+d+d_

def frombtree(data):
    w, d1 = fromleb128(data)
    trunk, d2 = fromleb128(data[d1:])
    block, d3 = fromleb128(data[d1+d2:])
    crc = fromle32(data[d1+d2+d3:])
    return w, trunk, block, crc

def popc(x):
    return bin(x).count('1')

def xxd(data, width=16, crc=False):
    for i in range(0, len(data), width):
        yield '%-*s %-*s' % (
            3*width,
            ' '.join('%02x' % b for b in data[i:i+width]),
            width,
            ''.join(
                b if b >= ' ' and b <= '~' else '.'
                for b in map(chr, data[i:i+width])))

def tagrepr(tag, w, size, off=None):
    if (tag & 0x7fff) == TAG_UNR:
        return 'unr%s%s' % (
            ' w%d' % w if w else '',
            ' %d' % size if size else '')
    elif (tag & 0x6fff) == TAG_SUPERMAGIC:
        return '%ssupermagic%s%s' % (
            'rm' if tag & 0x1000 else '',
            ' w%d' % w if w else '',
            ' %d' % size if not tag & 0x1000 or size else '')
    elif (tag & 0x6fff) == TAG_SUPERCONFIG:
        return '%ssuperconfig%s%s' % (
            'rm' if tag & 0x1000 else '',
            ' w%d' % w if w else '',
            ' %d' % size if not tag & 0x1000 or size else '')
    elif (tag & 0x6f00) == TAG_NAME:
        return '%s%s%s%s' % (
            'rm' if tag & 0x1000 else '',
            'branch' if (tag & 0xfffe) == TAG_BRANCH
                else 'reg' if (tag & 0xfffe) == TAG_REG
                else 'dir' if (tag & 0xfffe) == TAG_DIR
                else 'name 0x%02x' % ((tag & 0x0ff0) >> 4),
            ' w%d' % w if w else '',
            ' %d' % size if not tag & 0x1000 or size else '')
    elif (tag & 0x6f00) == TAG_STRUCT:
        return '%s%s%s%s' % (
            'rm' if tag & 0x1000 else '',
            'inlined' if (tag & 0x6fff) == TAG_INLINED
                else 'block' if (tag & 0x6fff) == TAG_BLOCK
                else 'btree' if (tag & 0x6fff) == TAG_BTREE
                else 'mdir' if (tag & 0x6fff) == TAG_MROOT
                else 'mdir' if (tag & 0x6fff) == TAG_MDIR
                else 'struct 0x%02x' % ((tag & 0x0ff0) >> 4),
            ' w%d' % w if w else '',
            ' %d' % size if not tag & 0x1000 or size else '')
    elif (tag & 0x6f00) == TAG_UATTR:
        return '%suattr 0x%02x%s%s' % (
            'rm' if tag & 0x1000 else '',
            tag & 0xff,
            ' w%d' % w if w else '',
            ' %d' % size if not tag & 0x1000 or size else '')
    elif (tag & 0x7f00) == TAG_CRC:
        return 'crc%x%s %d' % (
            1 if tag & 0x1 else 0,
            ' 0x%x' % w if w > 0 else '',
            size)
    elif (tag & 0x7fff) == TAG_FCRC:
        return 'fcrc%s %d' % (
            ' 0x%x' % w if w > 0 else '',
            size)
    elif tag & 0x4000:
        return 'alt%s%s 0x%x w%d %s' % (
            'r' if tag & 0x1000 else 'b',
            'gt' if tag & 0x2000 else 'le',
            tag & 0x0fff,
            w,
            '0x%x' % (0xffffffff & (off-size))
                if off is not None
                else '-%d' % off)
    else:
        return '0x%04x w%d %d' % (tag, w, size)


# this type is used for tree representations
TBranch = co.namedtuple('TBranch', 'a, b, d, c')

# our core rbyd type
class Rbyd:
    def __init__(self, block, data, rev, off, trunk, weight):
        self.block = block
        self.data = data
        self.rev = rev
        self.off = off
        self.trunk = trunk
        self.weight = weight
        self.other_blocks = []

    def addr(self):
        if not self.other_blocks:
            return '0x%x.%x' % (self.block, self.trunk)
        else:
            return '0x{%x,%s}.%x' % (
                self.block,
                ','.join('%x' % block for block in self.other_blocks),
                self.trunk)

    @classmethod
    def fetch(cls, f, block_size, blocks, trunk=None):
        if isinstance(blocks, int):
            blocks = [blocks]

        if len(blocks) > 1:
            # fetch all blocks
            rbyds = [cls.fetch(f, block_size, block, trunk) for block in blocks]
            # determine most recent revision
            i = 0
            for i_, rbyd in enumerate(rbyds):
                # compare with sequence arithmetic
                if rbyd and (
                        not ((rbyd.rev - rbyds[i].rev) & 0x80000000)
                        or (rbyd.rev == rbyds[i].rev
                            and rbyd.trunk > rbyds[i].trunk)):
                    i = i_
            # keep track of the other blocks
            rbyd = rbyds[i]
            rbyd.other_blocks = [rbyds[(i+1+j) % len(rbyds)].block
                for j in range(len(rbyds)-1)]
            return rbyd
        else:
            # block may encode a trunk
            block = blocks[0]
            if isinstance(block, tuple):
                if trunk is None:
                    trunk = block[1]
                block = block[0]

        # seek to the block
        f.seek(block * block_size)
        data = f.read(block_size)

        # fetch the rbyd
        rev = fromle32(data[0:4])
        crc = 0
        crc_ = crc32c(data[0:4])
        off = 0
        j_ = 4
        trunk_ = 0
        trunk__ = 0
        weight = 0
        lower_, upper_ = 0, 0
        weight_ = 0
        wastrunk = False
        trunkoff = None
        while j_ < len(data) and (not trunk or off <= trunk):
            v, tag, w, size, d = fromtag(data[j_:])
            if v != (popc(crc_) & 1):
                break
            crc_ = crc32c(data[j_:j_+d], crc_)
            j_ += d
            if not tag & 0x4000 and j_ + size > len(data):
                break

            # take care of crcs
            if not tag & 0x4000:
                if (tag & 0x7f00) != TAG_CRC:
                    crc_ = crc32c(data[j_:j_+size], crc_)
                # found a crc?
                else:
                    crc__ = fromle32(data[j_:j_+4])
                    if crc_ != crc__:
                        break
                    # commit what we have
                    off = trunkoff if trunkoff else j_ + size
                    crc = crc_
                    trunk_ = trunk__
                    weight = weight_

            # evaluate trunks
            if (tag & 0x6000) != 0x2000 and (
                    not trunk or trunk >= j_-d or wastrunk):
                # new trunk?
                if not wastrunk:
                    trunk__ = j_-d
                    lower_, upper_ = 0, 0
                    wastrunk = True

                # keep track of weight
                if tag & 0x4000:
                    if tag & 0x2000:
                        upper_ += w
                    else:
                        lower_ += w
                else:
                    weight_ = lower_+upper_+w
                    wastrunk = False
                    # keep track of off for best matching trunk
                    if trunk and j_ + size > trunk:
                        trunkoff = j_ + size

            if not tag & 0x4000:
                j_ += size

        return cls(block, data, rev, off, trunk_, weight)

    def lookup(self, id, tag):
        if not self:
            return True, 0, -1, 0, 0, 0, b'', []

        lower = -1
        upper = self.weight
        path = []

        # descend down tree
        j = self.trunk
        while True:
            _, alt, weight_, jump, d = fromtag(self.data[j:])

            # found an alt?
            if alt & 0x4000:
                # follow?
                if ((id, tag & 0xfff) > (upper-weight_-1, alt & 0xfff)
                        if alt & 0x2000
                        else ((id, tag & 0xfff)
                            <= (lower+weight_, alt & 0xfff))):
                    lower += upper-lower-1-weight_ if alt & 0x2000 else 0
                    upper -= upper-lower-1-weight_ if not alt & 0x2000 else 0
                    j = j - jump

                    # figure out which color
                    if alt & 0x1000:
                        _, nalt, _, _, _ = fromtag(self.data[j+jump+d:])
                        if nalt & 0x1000:
                            path.append((j+jump, j, True, 'y'))
                        else:
                            path.append((j+jump, j, True, 'r'))
                    else:
                        path.append((j+jump, j, True, 'b'))

                # stay on path
                else:
                    lower += weight_ if not alt & 0x2000 else 0
                    upper -= weight_ if alt & 0x2000 else 0
                    j = j + d

                    # figure out which color
                    if alt & 0x1000:
                        _, nalt, _, _, _ = fromtag(self.data[j:])
                        if nalt & 0x1000:
                            path.append((j-d, j, False, 'y'))
                        else:
                            path.append((j-d, j, False, 'r'))
                    else:
                        path.append((j-d, j, False, 'b'))

            # found tag
            else:
                id_ = upper-1
                tag_ = alt
                w_ = id_-lower

                done = (id_, tag_) < (id, tag) or tag_ & 0x1000

                return done, id_, tag_, w_, j, d, self.data[j+d:j+d+jump], path

    def __bool__(self):
        return bool(self.trunk)

    def __eq__(self, other):
        return self.block == other.block and self.trunk == other.trunk

    def __ne__(self, other):
        return not self.__eq__(other)

    def __iter__(self):
        tag = 0
        id = -1

        while True:
            done, id, tag, w, j, d, data, _ = self.lookup(id, tag+0x1)
            if done:
                break

            yield id, tag, w, j, d, data

    # create tree representation for debugging
    def tree(self):
        trunks = co.defaultdict(lambda: (-1, 0))
        alts = co.defaultdict(lambda: {})

        id, tag = -1, 0
        while True:
            done, id, tag, w, j, d, data, path = self.lookup(id, tag+0x1)
            # found end of tree?
            if done:
                break

            # keep track of trunks/alts
            trunks[j] = (id, tag)

            for j_, j__, followed, c in path:
                if followed:
                    alts[j_] |= {'f': j__, 'c': c}
                else:
                    alts[j_] |= {'nf': j__, 'c': c}

        # prune any alts with unreachable edges
        pruned = {}
        for j_, alt in alts.items():
            if 'f' not in alt:
                pruned[j_] = alt['nf']
            elif 'nf' not in alt:
                pruned[j_] = alt['f']
        for j_ in pruned.keys():
            del alts[j_]

        for j_, alt in alts.items():
            while alt['f'] in pruned:
                alt['f'] = pruned[alt['f']]
            while alt['nf'] in pruned:
                alt['nf'] = pruned[alt['nf']]

        # find the trunk and depth of each alt, assuming pruned alts
        # didn't exist
        def rec_trunk(j_):
            if j_ not in alts:
                return trunks[j_]
            else:
                if 'nft' not in alts[j_]:
                    alts[j_]['nft'] = rec_trunk(alts[j_]['nf'])
                return alts[j_]['nft']

        for j_ in alts.keys():
            rec_trunk(j_)
        for j_, alt in alts.items():
            if alt['f'] in alts:
                alt['ft'] = alts[alt['f']]['nft']
            else:
                alt['ft'] = trunks[alt['f']]

        def rec_height(j_):
            if j_ not in alts:
                return 0
            else:
                if 'h' not in alts[j_]:
                    alts[j_]['h'] = max(
                        rec_height(alts[j_]['f']),
                        rec_height(alts[j_]['nf'])) + 1
                return alts[j_]['h']

        for j_ in alts.keys():
            rec_height(j_)

        t_depth = max((alt['h']+1 for alt in alts.values()), default=0)

        # convert to more general tree representation
        tree = set()
        for j, alt in alts.items():
            # note all non-trunk edges should be black
            tree.add(TBranch(
                a=alt['nft'],
                b=alt['nft'],
                d=t_depth-1 - alt['h'],
                c=alt['c'],
            ))
            tree.add(TBranch(
                a=alt['nft'],
                b=alt['ft'],
                d=t_depth-1 - alt['h'],
                c='b',
            ))

        return tree, t_depth


def main(disk, roots=None, *,
        block_size=None,
        trunk=None,
        color='auto',
        **args):
    # figure out what color should be
    if color == 'auto':
        color = sys.stdout.isatty()
    elif color == 'always':
        color = True
    else:
        color = False

    # flatten roots, default to block 0
    if not roots:
        roots = [[0]]
    roots = [block for roots_ in roots for block in roots_]

    # we seek around a bunch, so just keep the disk open
    with open(disk, 'rb') as f:
        # if block_size is omitted, assume the block device is one big block
        if block_size is None:
            f.seek(0, os.SEEK_END)
            block_size = f.tell()

        # fetch the root
        btree = Rbyd.fetch(f, block_size, roots, trunk)
        print('btree %s, rev %d, weight %d' % (
            btree.addr(), btree.rev, btree.weight))

        # look up an id, while keeping track of the search path
        def btree_lookup(bid, depth=None):
            rbyd = btree
            rid = bid
            depth_ = 1
            path = []

            # corrupted? return a corrupted block once
            if not rbyd:
                return bid > 0, bid, 0, rbyd, -1, [], path

            while True:
                # collect all tags, normally you don't need to do this
                # but we are debugging here
                name = None
                tags = []
                branch = None
                rid_ = rid
                tag = 0
                w = 0
                for i in it.count():
                    done, rid__, tag, w_, j, d, data, _ = rbyd.lookup(
                        rid_, tag+0x1)
                    if done or (i != 0 and rid__ != rid_):
                        break

                    # first tag indicates the branch's weight
                    if i == 0:
                        rid_, w = rid__, w_

                    # catch any branches
                    if tag == TAG_BTREE:
                        branch = (tag, j, d, data)

                    tags.append((tag, j, d, data))

                # keep track of path
                path.append((bid + (rid_-rid), w, rbyd, rid_, tags))

                # descend down branch?
                if branch is not None and (
                        not depth or depth_ < depth):
                    tag, j, d, data = branch
                    w_, trunk, block, crc = frombtree(data)
                    rbyd = Rbyd.fetch(f, block_size, block, trunk)

                    # corrupted? bail here so we can keep traversing the tree
                    if not rbyd:
                        return False, bid + (rid_-rid), w, rbyd, -1, [], path

                    rid -= (rid_-(w-1))
                    depth_ += 1
                else:
                    return not tags, bid + (rid_-rid), w, rbyd, rid_, tags, path

        # precompute rbyd-trees if requested
        t_width = 0
        if args.get('tree'):
            # find the max depth of each layer to nicely align trees
            bdepths = {}
            bid = -1
            while True:
                done, bid, w, rbyd, rid, tags, path = btree_lookup(
                    bid+1, depth=args.get('depth'))
                if done:
                    break

                for d, (bid, w, rbyd, rid, tags) in enumerate(path):
                    _, rdepth = rbyd.tree()
                    bdepths[d] = max(bdepths.get(d, 0), rdepth)

            # find all branches
            tree = set()
            root = None
            branches = {}
            bid = -1
            while True:
                done, bid, w, rbyd, rid, tags, path = btree_lookup(
                    bid+1, depth=args.get('depth'))
                if done:
                    break

                d_ = 0
                leaf = None
                for d, (bid, w, rbyd, rid, tags) in enumerate(path):
                    if not tags:
                        continue

                    # map rbyd tree into B-tree space
                    rtree, rdepth = rbyd.tree()

                    # note we adjust our bid/rids to be left-leaning,
                    # this allows a global order and make tree rendering quite
                    # a bit easier
                    rtree_ = set()
                    for branch in rtree:
                        a_rid, a_tag = branch.a
                        b_rid, b_tag = branch.b
                        _, _, _, a_w, _, _, _, _ = rbyd.lookup(a_rid, 0)
                        _, _, _, b_w, _, _, _, _ = rbyd.lookup(b_rid, 0)
                        rtree_.add(TBranch(
                            a=(a_rid-(a_w-1), a_tag),
                            b=(b_rid-(b_w-1), b_tag),
                            d=branch.d,
                            c=branch.c,
                        ))
                    rtree = rtree_

                    # connect our branch to the rbyd's root
                    if leaf is not None:
                        root = min(rtree,
                            key=lambda branch: branch.d,
                            default=None)

                        if root is not None:
                            r_rid, r_tag = root.a
                        else:
                            r_rid, r_tag = rid-(w-1), tags[0][0]
                        tree.add(TBranch(
                            a=leaf,
                            b=(bid-rid+r_rid, d, r_rid, r_tag),
                            d=d_-1,
                            c='b',
                        ))

                    for branch in rtree:
                        # map rbyd branches into our btree space
                        a_rid, a_tag = branch.a
                        b_rid, b_tag = branch.b
                        tree.add(TBranch(
                            a=(bid-rid+a_rid, d, a_rid, a_tag),
                            b=(bid-rid+b_rid, d, b_rid, b_tag),
                            d=branch.d + d_ + bdepths.get(d, 0)-rdepth,
                            c=branch.c,
                        ))

                    d_ += max(bdepths.get(d, 0), 1)
                    leaf = (bid-(w-1), d, rid-(w-1), TAG_BTREE)

            # remap branches to leaves if we aren't showing inner branches
            if not args.get('inner'):
                # step through each layer backwards
                b_depth = max((branch.b[1]+1 for branch in tree), default=0)

                # keep track of the original bids, unfortunately because we
                # store the bids in the branches we overwrite these
                tree = {(branch.b[0] - branch.b[2], branch) for branch in tree}

                for bd in reversed(range(b_depth-1)):
                    # find leaf-roots at this level
                    roots = {}
                    for bid, branch in tree:
                        # choose the highest node as the root
                        if (branch.b[1] == b_depth-1
                                and (bid not in roots
                                    or branch.d < roots[bid].d)):
                            roots[bid] = branch

                    # remap branches to leaf-roots
                    tree_ = set()
                    for bid, branch in tree:
                        if branch.a[1] == bd and branch.a[0] in roots:
                            branch = TBranch(
                                a=roots[branch.a[0]].b,
                                b=branch.b,
                                d=branch.d,
                                c=branch.c,
                            )
                        if branch.b[1] == bd and branch.b[0] in roots:
                            branch = TBranch(
                                a=branch.a,
                                b=roots[branch.b[0]].b,
                                d=branch.d,
                                c=branch.c,
                            )
                        tree_.add((bid, branch))
                    tree = tree_

                # strip out bids
                tree = {branch for _, branch in tree}

        # precompute B-trees if requested
        elif args.get('btree'):
            # find all branches
            tree = set()
            root = None
            branches = {}
            bid = -1
            while True:
                done, bid, w, rbyd, rid, tags, path = btree_lookup(
                    bid+1, depth=args.get('depth'))
                if done:
                    break

                # if we're not showing inner nodes, prefer names higher in
                # the tree since this avoids showing vestigial names
                name = None
                if not args.get('inner'):
                    name = None
                    for bid_, w_, rbyd_, rid_, tags_ in reversed(path):
                        for tag_, j_, d_, data_ in tags_:
                            if tag_ & 0x7f00 == TAG_NAME:
                                name = (tag_, j_, d_, data_)

                        if rid_-(w_-1) != 0:
                            break

                a = root
                for d, (bid, w, rbyd, rid, tags) in enumerate(path):
                    if not tags:
                        continue

                    b = (bid-(w-1), d, rid-(w-1),
                        (name if name else tags[0])[0])

                    # remap branches to leaves if we aren't showing
                    # inner branches
                    if not args.get('inner'):
                        if b not in branches:
                            bid, w, rbyd, rid, tags = path[-1]
                            if not tags:
                                continue
                            branches[b] = (
                                bid-(w-1), len(path)-1, rid-(w-1),
                                (name if name else tags[0])[0])
                        b = branches[b]

                    # found entry point?
                    if root is None:
                        root = b
                        a = root

                    tree.add(TBranch(
                        a=a,
                        b=b,
                        d=d,
                        c='b',
                    ))
                    a = b

        # common tree renderer
        if args.get('tree') or args.get('btree'):
            # find the max depth from the tree
            t_depth = max((branch.d+1 for branch in tree), default=0)
            if t_depth > 0:
                t_width = 2*t_depth + 2

            def treerepr(bid, w, bd, rid, tag):
                if t_depth == 0:
                    return ''

                def branchrepr(x, d, was):
                    for branch in tree:
                        if branch.d == d and branch.b == x:
                            if any(branch.d == d and branch.a == x
                                    for branch in tree):
                                return '+-', branch.c, branch.c
                            elif any(branch.d == d
                                    and x > min(branch.a, branch.b)
                                    and x < max(branch.a, branch.b)
                                    for branch in tree):
                                return '|-', branch.c, branch.c
                            elif branch.a < branch.b:
                                return '\'-', branch.c, branch.c
                            else:
                                return '.-', branch.c, branch.c
                    for branch in tree:
                        if branch.d == d and branch.a == x:
                            return '+ ', branch.c, None
                    for branch in tree:
                        if (branch.d == d
                                and x > min(branch.a, branch.b)
                                and x < max(branch.a, branch.b)):
                            return '| ', branch.c, was
                    if was:
                        return '--', was, was
                    return '  ', None, None

                trunk = []
                was = None
                for d in range(t_depth):
                    t, c, was = branchrepr(
                        (bid-(w-1), bd, rid-(w-1), tag), d, was)

                    trunk.append('%s%s%s%s' % (
                        '\x1b[33m' if color and c == 'y'
                            else '\x1b[31m' if color and c == 'r'
                            else '\x1b[90m' if color and c == 'b'
                            else '',
                        t,
                        ('>' if was else ' ') if d == t_depth-1 else '',
                        '\x1b[m' if color and c else ''))

                return '%s ' % ''.join(trunk)


        # print header
        w_width = 2*m.ceil(m.log10(max(1, btree.weight)+1))+1
        print('%-9s  %*s%-*s %-22s  %s' % (
            'rbyd',
            t_width, '',
            w_width, 'ids',
            'tag',
            'data (truncated)'
                if not args.get('no_truncate') else ''))

        # prbyd here means the last rendered rbyd, we update
        # in dbg_branch to always print interleaved addresses
        prbyd = None
        def dbg_branch(bid, w, rbyd, rid, tags, bd):
            nonlocal prbyd

            # show human-readable representation
            for i, (tag, j, d, data) in enumerate(tags):
                print('%10s %s%*s %-22s  %s' % (
                    '%04x.%04x:' % (rbyd.block, rbyd.trunk)
                        if prbyd is None or rbyd != prbyd
                        else '',
                    treerepr(bid, w, bd, rid, tag)
                        if args.get('tree') or args.get('btree') else '',
                    w_width, '' if i != 0
                        else '%d-%d' % (bid-(w-1), bid) if w > 1
                        else bid if w > 0
                        else '',
                    tagrepr(tag, w if i == 0 else 0, len(data), None),
                    # note we render names a bit different here
                    ''.join(
                        b if b >= ' ' and b <= '~' else '.'
                        for b in map(chr, data))
                            if tag & 0x7f00 == TAG_NAME
                        else next(xxd(data, 8), '')
                            if not args.get('no_truncate')
                        else ''))
                prbyd = rbyd

            # show in-device representation
            if args.get('device'):
                for i, (tag, j, d, data) in enumerate(tags):
                    print('%9s  %*s%*s %-22s%s' % (
                        '',
                        t_width, '',
                        w_width, '',
                        '%04x %08x %07x' % (tag, w if i == 0 else 0, len(data)),
                        '  %s' % ' '.join(
                            '%08x' % fromle32(
                                rbyd.data[j+d+i*4 : j+d + min(i*4+4,len(data))])
                            for i in range(min(m.ceil(len(data)/4), 3)))[:23]))

            # show on-disk encoding of tags/data
            for i, (tag, j, d, data) in enumerate(tags):
                if args.get('raw'):
                    for o, line in enumerate(xxd(rbyd.data[j:j+d])):
                        print('%9s: %*s%*s %s' % (
                            '%04x' % (j + o*16),
                            t_width, '',
                            w_width, '',
                            line))
                # note we don't render name tags with no_truncate
                if args.get('raw') or (
                        args.get('no_truncate') and tag & 0xf00f != TAG_NAME):
                    for o, line in enumerate(xxd(data)):
                        print('%9s: %*s%*s %s' % (
                            '%04x' % (j+d + o*16),
                            t_width, '',
                            w_width, '',
                            line))


        # traverse and print entries
        bid = -1
        prbyd = None
        ppath = []
        corrupted = False
        while True:
            done, bid, w, rbyd, rid, tags, path = btree_lookup(
                bid+1, depth=args.get('depth'))
            if done:
                break

            # print inner btree entries if requested
            if args.get('inner'):
                changed = False
                for (x, px) in it.zip_longest(
                        enumerate(path[:-1]),
                        enumerate(ppath[:-1])):
                    if x is None:
                        break
                    if not (changed or px is None or x != px):
                        continue
                    changed = True

                    # show the inner entry
                    d, (bid_, w_, rbyd_, rid_, tags_) = x
                    dbg_branch(bid_, w_, rbyd_, rid_, tags_, d)
            ppath = path

            # corrupted? try to keep printing the tree
            if not rbyd:
                print('%04x.%04x: %*s%s%s%s' % (
                    rbyd.block, rbyd.trunk,
                    t_width, '',
                    '\x1b[31m' if color else '',
                    '(corrupted rbyd %s)' % rbyd.addr(),
                    '\x1b[m' if color else ''))
                prbyd = rbyd
                corrupted = True
                continue

            # if we're not showing inner nodes, prefer names higher in the tree
            # since this avoids showing vestigial names
            if not args.get('inner'):
                name = None
                for bid_, w_, rbyd_, rid_, tags_ in reversed(path):
                    for tag_, j_, d_, data_ in tags_:
                        if tag_ & 0x7f00 == TAG_NAME:
                            name = (tag_, j_, d_, data_)

                    if rid_-(w_-1) != 0:
                        break

                if name is not None:
                    tags = [name] + [(tag, j, d, data)
                        for tag, j, d, data in tags
                        if tag & 0x7f00 != TAG_NAME]

            # show the branch
            dbg_branch(bid, w, rbyd, rid, tags, len(path)-1)

        if args.get('error_on_corrupt') and corrupted:
            sys.exit(2)


if __name__ == "__main__":
    import argparse
    import sys
    parser = argparse.ArgumentParser(
        description="Debug rbyd B-trees.",
        allow_abbrev=False)
    parser.add_argument(
        'disk',
        help="File containing the block device.")
    parser.add_argument(
        'roots',
        nargs='*',
        type=rbydaddr,
        help="Block address of the roots of the tree.")
    parser.add_argument(
        '-B', '--block-size',
        type=lambda x: int(x, 0),
        help="Block size in bytes.")
    parser.add_argument(
        '--trunk',
        type=lambda x: int(x, 0),
        help="Use this offset as the trunk of the tree.")
    parser.add_argument(
        '--color',
        choices=['never', 'always', 'auto'],
        default='auto',
        help="When to use terminal colors. Defaults to 'auto'.")
    parser.add_argument(
        '-r', '--raw',
        action='store_true',
        help="Show the raw data including tag encodings.")
    parser.add_argument(
        '-x', '--device',
        action='store_true',
        help="Show the device-side representation of tags.")
    parser.add_argument(
        '-T', '--no-truncate',
        action='store_true',
        help="Don't truncate, show the full contents.")
    parser.add_argument(
        '-i', '--inner',
        action='store_true',
        help="Show inner branches.")
    parser.add_argument(
        '-t', '--tree',
        action='store_true',
        help="Show the underlying rbyd trees.")
    parser.add_argument(
        '-b', '--btree',
        action='store_true',
        help="Show the underlying B-tree.")
    parser.add_argument(
        '-Z', '--depth',
        type=lambda x: int(x, 0),
        help="Depth of tree to show.")
    parser.add_argument(
        '-e', '--error-on-corrupt',
        action='store_true',
        help="Error if B-tree is corrupt.")
    sys.exit(main(**{k: v
        for k, v in vars(parser.parse_intermixed_args()).items()
        if v is not None}))
