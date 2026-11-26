"""Request-local performance diagnostics; never logs payloads or SQL parameters."""
from contextvars import ContextVar
from contextlib import contextmanager
from functools import wraps
import logging
import os
import re
from time import perf_counter
from uuid import uuid4

log=logging.getLogger(__name__)
_current=ContextVar('dhl_performance',default=None)

def database_failure(exc):
    data=_current.get() or {};original=getattr(exc,'orig',exc)
    log.warning('dhl_database_failure request_id=%s sqlstate=%s driver_error=%s',
        data.get('request_id','outside_request'),getattr(original,'sqlstate',None),type(original).__name__)

@contextmanager
def phase(name):
    data=_current.get();start=perf_counter()
    try:yield
    finally:
        if data is not None:
            data['phases'][name]=data['phases'].get(name,0)+(perf_counter()-start)*1000

def timed(name):
    def decorate(fn):
        @wraps(fn)
        def call(*args,**kwargs):
            with phase(name):return fn(*args,**kwargs)
        return call
    return decorate


def install(app,engine=None):
    if getattr(app.state,'dhl_performance_installed',False):return
    app.state.dhl_performance_installed=True
    if not log.handlers:
        handler=logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(levelname)s %(name)s %(message)s'))
        log.addHandler(handler)
    log.setLevel(logging.INFO);log.propagate=False
    if engine is not None and not getattr(engine,'_dhl_performance_installed',False):
        engine._dhl_performance_installed=True
        from sqlalchemy import event
        @event.listens_for(engine,'before_cursor_execute')
        def before(conn,cursor,statement,parameters,context,executemany):
            if _current.get() is not None:context._dhl_started=perf_counter()
        @event.listens_for(engine,'after_cursor_execute')
        def after(conn,cursor,statement,parameters,context,executemany):
            data=_current.get();start=getattr(context,'_dhl_started',None)
            if data is not None and start is not None:
                data['queries']+=1;data['phases']['database']=data['phases'].get('database',0)+(perf_counter()-start)*1000
    @app.middleware('http')
    async def measure(request,call_next):
        if not request.url.path.startswith('/dhl-reports'):return await call_next(request)
        identifier=uuid4().hex;data={'request_id':identifier,'phases':{},'queries':0};token=_current.set(data);start=perf_counter();status=500
        try:
            response=await call_next(request);status=response.status_code
            response.headers['X-Request-ID']=identifier
            release=os.environ.get('RENDER_GIT_COMMIT','')
            if re.fullmatch('[0-9a-fA-F]{40}',release):response.headers['X-Release-Commit']=release.lower()
            response.headers['Server-Timing']=', '.join(f'{k};dur={v:.2f}' for k,v in data['phases'].items())
            return response
        finally:
            route=request.scope.get('route');pattern=getattr(route,'path','unmatched')
            log.info('dhl_performance request_id=%s method=%s route=%s status=%s duration_ms=%.2f sql_queries=%s phases=%s',
                identifier,request.method,pattern,status,(perf_counter()-start)*1000,data['queries'],
                {k:round(v,2) for k,v in data['phases'].items()})
            _current.reset(token)
