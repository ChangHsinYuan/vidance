"""v13 门面：真实实现已移至 agents.post.tools.gen_luts（原路径兼容转发）。"""
import importlib as _il, sys as _sys
if __name__ == '__main__':
    import os as _os
    import runpy as _rp
    _r = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    if _r not in _sys.path:
        _sys.path.insert(0, _r)
    _rp.run_module('agents.post.tools.gen_luts', run_name='__main__', alter_sys=True)
    _sys.exit(0)
_sys.modules[__name__] = _il.import_module('agents.post.tools.gen_luts')
