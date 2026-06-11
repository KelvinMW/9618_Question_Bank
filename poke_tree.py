from dataclasses import dataclass

@dataclass
class Pokemon:
    name : str
    type : str
    number : int

@dataclass
class PokeNode:
    data : Pokemon
    left : PokeNode
    right : PokeNode

class PokeTree:

    def __init__(self):
        self._root = None

    def traverse(self):
        curr = self._root
        while (curr is not None):
            print(curr)
            curr = curr.next

    def insert(self, pokemon : Pokemon):
        _root = Pokenode(pokemon, None, None)

bulb = Pokemon("Bulbasaur", "Grass", 1)
tree = PokeTree()
tree.traverse()
