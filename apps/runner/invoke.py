"""Unprivileged invocation adapter. Its return value alone cannot approve a lab."""
import contextlib
import importlib.util
import json
import sys

request=json.load(sys.stdin)
spec=importlib.util.spec_from_file_location('participant_handler',request['path'])
module=importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(sys.stderr):
    spec.loader.exec_module(module)
    result=module.handler(request['event'],None)
json.dump(result,sys.stdout)
