import ktl.colored

class Color():
    no_color = False

    LIGHT = False
    DARK  = True
    if LIGHT:
        COLOR_DEFAULT     = ktl.colored.fg('black')
        COLOR_SERIES      = ktl.colored.fg('green') + ktl.colored.attr('bold')
        COLOR_PACKAGE     = ktl.colored.fg('yellow_4a')
        COLOR_BG_ODD      = ktl.colored.bg('white')
        COLOR_BG_EVEN     = ktl.colored.bg('wheat_1')

    if DARK:
        COLOR_DEFAULT     = ktl.colored.fg('white')
        COLOR_SERIES      = ktl.colored.fg('green') + ktl.colored.attr('bold')
        COLOR_PACKAGE     = ktl.colored.fg('yellow_1')
        COLOR_BG_ODD      = ktl.colored.bg('black')
        COLOR_BG_EVEN     = ktl.colored.bg('grey_11')
        COLOR_TITLE       = ktl.colored.fg('yellow_1') + ktl.colored.attr('bold')
        COLOR_SHADOW      = ktl.colored.fg('grey_23') + ktl.colored.attr('bold')

    COLOR_DELTA       = ktl.colored.fg('cyan')
    COLOR_TASK_HEADER = ktl.colored.fg('blue')
    COLOR_EXCEEDS_THREASHOLD  = ktl.colored.fg('magenta_1') + ktl.colored.attr('bold')

    @classmethod
    def style(cls, text, color):
        if not cls.no_color:
            return ktl.colored.stylize(text, color)
        return text

    @classmethod
    def fg(cls, color):
        return ktl.colored.fg(color)
