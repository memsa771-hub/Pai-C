"""Static internal import graph, including function-local imports and literals.

Used before product moves. Every relative import and package initializer is
included; dynamic imports with literal module names are included. Nonliteral
imports are reported for review rather than silently treated as isolated.
"""
import argparse
import ast
import importlib
import json
from pathlib import Path


def graph(root):
    modules={}
    for file in sorted(root.rglob('*.py')):
        parts=file.relative_to(root.parent).with_suffix('').parts
        name='.'.join(parts[:-1] if parts[-1]=='__init__' else parts)
        modules[name]=file
    edges={name:set() for name in modules}; unresolved=[]
    def add(source,target):
        while target and target not in modules:
            target=target.rpartition('.')[0]
        if target.startswith('app') and target in modules:
            edges[source].add(target)
    for name,file in modules.items():
        package=name if file.name=='__init__.py' else name.rpartition('.')[0]
        if name!='app': add(name,package)
        for node in ast.walk(ast.parse(file.read_text(encoding='utf-8-sig'))):
            if isinstance(node,ast.Import):
                for alias in node.names: add(name,alias.name)
            elif isinstance(node,ast.ImportFrom):
                target=node.module or ''
                if node.level:
                    parts=package.split('.')
                    target='.'.join(parts[:len(parts)-node.level+1]+([target] if target else []))
                add(name,target)
                for alias in node.names:
                    if target+'.'+alias.name in modules: add(name,target+'.'+alias.name)
            elif isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='import_module':
                if node.args and isinstance(node.args[0],ast.Constant): add(name,node.args[0].value)
                elif name=='app.capabilities.loader':
                    for bundled in modules:
                        if bundled.startswith('app.plugins.') and bundled.count('.')==2: add(name,bundled)
                else: unresolved.append({'module':name,'line':node.lineno})
    return modules,edges,unresolved


def reachable(edges,starts):
    seen=set(starts); pending=list(starts)
    while pending:
        for item in edges.get(pending.pop(),()):
            if item not in seen: seen.add(item); pending.append(item)
    return seen


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--import-all',action='store_true')
    parser.add_argument('--out',type=Path)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]/'app'
    modules,edges,unresolved=graph(root)
    starts={name for name in modules if name.startswith('app.pai_c')}
    found=reachable(edges,starts)
    candidates={name for name in modules if name.startswith(('app.application_workspace','app.deadlines','app.services.workflow','app.pai_os'))}
    imported=[]
    if args.import_all:
        for name in sorted(modules): importlib.import_module(name); imported.append(name)
    result={'modules':len(modules),'counselor_roots':sorted(starts),'reachable':sorted(found),
        'os_candidates':sorted(candidates),'os_eligible':sorted(candidates-found),
        'os_ineligible':sorted(candidates & found),'dynamic_imports_requiring_review':unresolved,
        'edges':{name:sorted(targets) for name,targets in edges.items()},'imported_count':len(imported)}
    if args.out: args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({key:result[key] for key in ['modules','imported_count','os_eligible','os_ineligible','dynamic_imports_requiring_review']}))


if __name__=='__main__': main()
