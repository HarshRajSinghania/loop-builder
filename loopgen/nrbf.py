"""Read NRBF data records without instantiating serialized .NET classes."""

import io
import struct
from dataclasses import dataclass


class FormatError(ValueError):
    pass


@dataclass
class Reference:
    object_id: int


@dataclass
class NullRun:
    count: int


@dataclass
class Object:
    class_name: str
    members: dict


class Reader:
    def __init__(self, data):
        self.stream = io.BytesIO(data)
        self.objects = {}
        self.classes = {}
        self.libraries = {}
        self.root_id = None
        self.ended = False

    def read(self, size):
        value = self.stream.read(size)
        if len(value) != size:
            raise FormatError("Unexpected end of NRBF stream")
        return value

    def number(self, code):
        return struct.unpack("<" + code, self.read(struct.calcsize("<" + code)))[0]

    def length(self):
        value = 0
        for shift in range(0, 35, 7):
            byte = self.number("B")
            value |= (byte & 127) << shift
            if not byte & 128:
                if value > 0x7FFFFFFF:
                    raise FormatError("Invalid string length")
                return value
        raise FormatError("Invalid length prefix")

    def string(self):
        return self.read(self.length()).decode("utf-8")

    def count(self):
        value = self.number("i")
        if not 0 <= value <= len(self.stream.getbuffer()):
            raise FormatError("Invalid collection size")
        return value

    def primitive(self, kind):
        codes = {
            1: "?",
            2: "B",
            6: "d",
            7: "h",
            8: "i",
            9: "q",
            10: "b",
            11: "f",
            12: "q",
            13: "Q",
            14: "H",
            15: "I",
            16: "Q",
        }
        if kind in codes:
            return self.number(codes[kind])
        if kind in (5, 18):
            return self.string()
        if kind == 17:
            return None
        if kind == 3:
            first = self.read(1)
            size = 1 if first[0] < 128 else (2 if first[0] < 224 else 3 if first[0] < 240 else 4)
            return (first + self.read(size - 1)).decode("utf-8")
        raise FormatError("Unsupported primitive type: %s" % kind)

    def type_info(self, kind):
        if kind in (0, 7):
            return self.number("B")
        if kind == 3:
            return self.string()
        if kind == 4:
            return (self.string(), self.number("i"))
        if kind in (1, 2, 5, 6):
            return None
        raise FormatError("Unknown binary type: %s" % kind)

    def value(self):
        while True:
            kind = self.number("B")
            if kind == 12:
                library_id = self.number("i")
                self.libraries[library_id] = self.string()
                continue
            return self.record(kind)

    def members(self, object_id, metadata):
        name, names, types, info = metadata
        obj = Object(name, {})
        self.objects[object_id] = obj
        for member, kind, extra in zip(names, types, info):
            obj.members[member] = self.primitive(extra) if kind == 0 else self.value()
        return obj

    def array_values(self, size, kind, info):
        if kind == 0:
            if info == 2:
                return self.read(size)
            return [self.primitive(info) for _ in range(size)]
        values = []
        while len(values) < size:
            value = self.value()
            if isinstance(value, NullRun):
                if not 1 <= value.count <= size - len(values):
                    raise FormatError("Invalid null run in array")
                values.extend([None] * value.count)
            else:
                values.append(value)
        return values

    def record(self, kind):
        if kind == 0:
            if self.root_id is not None:
                raise FormatError("Duplicate NRBF header")
            self.root_id = self.number("i")
            self.number("i")
            if (self.number("i"), self.number("i")) != (1, 0):
                raise FormatError("Unsupported NRBF version")
            return None
        if kind == 1:
            object_id = self.number("i")
            metadata_id = self.number("i")
            if metadata_id not in self.classes:
                raise FormatError("Missing class metadata: %s" % metadata_id)
            return self.members(object_id, self.classes[metadata_id])
        if kind in (2, 3, 4, 5):
            object_id = self.number("i")
            name = self.string()
            names = [self.string() for _ in range(self.count())]
            types = [self.number("B") for _ in names] if kind in (4, 5) else [2] * len(names)
            info = [self.type_info(t) for t in types]
            if kind in (3, 5):
                self.number("i")
            metadata = (name, names, types, info)
            self.classes[object_id] = metadata
            return self.members(object_id, metadata)
        if kind == 6:
            object_id = self.number("i")
            value = self.string()
            self.objects[object_id] = value
            return value
        if kind == 7:
            object_id = self.number("i")
            array_type = self.number("B")
            rank = self.count()
            if not 1 <= rank <= 32 or array_type not in range(6):
                raise FormatError("Invalid array shape")
            lengths = [self.count() for _ in range(rank)]
            if array_type in (3, 4, 5):
                for _ in range(rank):
                    self.number("i")
            element_type = self.number("B")
            info = self.type_info(element_type)
            size = 1
            for length in lengths:
                size *= length
            if size > len(self.stream.getbuffer()):
                raise FormatError("Array exceeds stream size")
            value = self.array_values(size, element_type, info)
            self.objects[object_id] = value
            return value
        if kind == 8:
            return self.primitive(self.number("B"))
        if kind == 9:
            return Reference(self.number("i"))
        if kind == 10:
            return None
        if kind == 11:
            self.ended = True
            return None
        if kind in (13, 14):
            return NullRun(self.number("B" if kind == 13 else "i"))
        if kind in (15, 16, 17):
            object_id = self.number("i")
            size = self.count()
            element_type = 0 if kind == 15 else 2 if kind == 16 else 1
            info = self.number("B") if kind == 15 else None
            value = self.array_values(size, element_type, info)
            self.objects[object_id] = value
            return value
        raise FormatError("Unsupported NRBF record %s at offset %s" % (kind, self.stream.tell() - 1))

    def parse(self):
        if self.number("B") != 0:
            raise FormatError("Not an NRBF stream")
        self.record(0)
        while not self.ended:
            self.value()
        if self.stream.read(1):
            raise FormatError("Trailing bytes after NRBF MessageEnd")
        return self.resolve(Reference(self.root_id))

    def resolve(self, value):
        seen = set()
        while isinstance(value, Reference):
            if value.object_id in seen or value.object_id not in self.objects:
                raise FormatError("Invalid object reference: %s" % value.object_id)
            seen.add(value.object_id)
            value = self.objects[value.object_id]
        return value

    def field(self, obj, name, default=None):
        obj = self.resolve(obj)
        if not isinstance(obj, Object):
            return default
        for key, value in obj.members.items():
            if key == name or key.endswith("+" + name) or key.endswith("<" + name + ">k__BackingField"):
                return self.resolve(value)
        return default
