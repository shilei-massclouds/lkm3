from engine import System


class Kernel(System):
    def boot(self, sig: Signal):
        print("boot")
