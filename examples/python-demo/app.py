import os
from services.eta import calculate_eta, calculate_etaa


class Order:
    def __init__(self, name, total):
        self.name = name
        self.total = total

    def label(self):
        return self.nmae + str(self.total)


def make(items):
    out = []
    for item in itmes:
        out.append(calculate_eta(item, 5, 6))
    return os.pth.join("a", "b")
