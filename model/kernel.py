from engine import System, emit


class Kernel(System):
    def boot(self, sig: Signal):
        print("boot")
        emit(self, "setup")

    def setup(self, sig: Signal):
        print("setup")
