import cairo


def solid_surface(width, height, rgb=(1, 1, 1)):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    cr.set_source_rgb(*rgb)
    cr.paint()
    surface.flush()
    return surface


def checker_surface(width, height, cell=4):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            value = 1.0 if (x // cell + y // cell) % 2 else 0.0
            cr.set_source_rgb(value, value, value)
            cr.rectangle(x, y, cell, cell)
            cr.fill()
    surface.flush()
    return surface


def pixel(surface, x, y):
    """Return (r, g, b, a) as 0-255 ints for the ARGB32 pixel at (x, y)."""
    surface.flush()
    data = surface.get_data()
    offset = y * surface.get_stride() + x * 4
    b, g, r, a = data[offset], data[offset + 1], data[offset + 2], data[offset + 3]
    return r, g, b, a
