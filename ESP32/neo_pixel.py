import machine
import neopixel
import urandom

class NeoPixelController:
    def __init__(self, pin_num, num_pixels=1, brightness=1.0):
        self.pin = machine.Pin(pin_num, machine.Pin.OUT)
        self.num_pixels = num_pixels
        self.brightness = max(0, min(brightness, 1.0))  # Clamp between 0 and 1
        self.np = neopixel.NeoPixel(self.pin, self.num_pixels)

    def _apply_brightness(self, color):
        """Apply brightness scaling to an (R, G, B) color tuple."""
        return tuple(int(c * self.brightness) for c in color)

    def show_color(self, color):
        """Set all pixels to a specific color."""
        dimmed = self._apply_brightness(color)
        for i in range(self.num_pixels):
            self.np[i] = dimmed
        self.np.write()

    def random_color(self):
        """Set all pixels to a random color."""
        color = (
            urandom.getrandbits(8),
            urandom.getrandbits(8),
            urandom.getrandbits(8)
        )
        self.show_color(color)

    def set_brightness(self, brightness):
        """Change brightness dynamically (0.0 to 1.0)."""
        self.brightness = max(0, min(brightness, 1.0))

if __name__ == "__main__":
    np = NeoPixelController(brightness=0.1)
    np.random_color()
