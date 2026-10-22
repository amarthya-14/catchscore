# Python imports this at startup when the directory is on PYTHONPATH. catchscore only puts it there
# while tracing, so that processes a test starts (e.g. a CLI under test) are traced too.
import _catchscore_tracer

_catchscore_tracer.start_child()
