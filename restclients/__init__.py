"""Small, readable REST client building blocks."""
import logging

# A library should not configure logging; this silences the "no handlers" warning
# and leaves the decision to the application.
logging.getLogger(__name__).addHandler(logging.NullHandler())
