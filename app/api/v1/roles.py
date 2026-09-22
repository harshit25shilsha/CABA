from enum import Enum

class Role(str, Enum):
    ADMIN = "ADMIN"
    CA = "CA"
    SUB_CA  = "SUB_CA"
    CLIENT = " CLIENT"