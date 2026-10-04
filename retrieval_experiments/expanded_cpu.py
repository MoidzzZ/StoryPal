"""Frozen v2.1 new story cases; bounded CPU encoding and fixed cached pack audit."""
from __future__ import annotations
import argparse, ctypes, hashlib, json, os, sys, time
from pathlib import Path
from . import cpu_routes as cpu, cache_audit as audit
from .holdout_contract import canonical, source_rows
from .cached_context_pack import source_evidence, terms
from .fusion_replay import rank_candidates
from .sparse import _tokens


def low_priority():
    if os.name != 'nt':
        return 'unchanged'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000):
        raise ctypes.WinError(ctypes.get_last_error())
    return 'BELOW_NORMAL_PRIORITY_CLASS'


def new_cases():
    audit.validate_business()
    payload = json.loads(audit.CONTRACT.read_text(encoding='utf-8'))
    output = []
    for t in payload['tasks']:
        if t['task_domain'] != 'story_retrieval' or int(t['task_id'][1:]) < 16:
            continue
        for v in t['variants']:
            output.append(dict(case_id=v['variant_id'], task_id=t['task_id'], set='prospective',
                group=t['split_group'], query=v['text'], max_order=t['max_order'],
                required_units=t['necessary_unit_candidates'], acceptable_evidence_sets=t['acceptable_evidence_sets'],
                provisional=True, decision='search', source_status='provisional'))
    if len(output) != 18 or len({c['task_id'] for c in output}) != 9:
        raise ValueError('New frozen case scope changed')
    return output


def dense(output):
    cases = new_cases()
    cpu.cpu_environment()
    os.environ.update(OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', RAYON_NUM_THREADS='2', ARROW_NUM_THREADS='2')
    priority = low_priority()
    import torch
    from sentence_transformers import SentenceTransformer
    sys.path.insert(0, str(cpu.PIPELINE))
    from storypipe.vector_index import read_vector_meta, search_vector_index
    torch.set_num_threads(2); torch.set_num_interop_threads(1)
    meta = read_vector_meta(cpu.VECTOR_DB)
    if (meta.get('source_sha256') != cpu.digest(cpu.SOURCE) or meta.get('dimension') != 1024
            or Path(meta.get('model', '')).resolve() != cpu.BGE.resolve()):
        raise ValueError('Index source/model differs')
    report = dict(schema='expanded-cpu-dense@1', source_sha256=cpu.digest(cpu.SOURCE),
        contract_sha256=canonical(json.loads(audit.CONTRACT.read_text(encoding='utf-8'))), vector_metadata=meta,
        device='cpu', threads=2, interop_threads=1, batch_size=2, priority=priority, cases=[], batches=[],
        query_encodings=0, scope_searches=0, status='loading', started_at_unix=time.time(), new_provider_requests=0,
        cost_stop=dict(compute_seconds=600, rss_bytes=12 * 1024**3))
    checkpoint = output.with_suffix('.progress.jsonl'); start = time.perf_counter(); compute = 0.0
    def log(event):
        with checkpoint.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n'); stream.flush(); os.fsync(stream.fileno())
    try:
        model = SentenceTransformer(str(cpu.BGE), device='cpu', local_files_only=True)
        if any(p.device.type != 'cpu' for p in model.parameters()):
            raise ValueError('Embedding device is not CPU')
        report.update(load_ms=(time.perf_counter() - start)*1000, load_memory=cpu.memory_stats())
        if report['load_memory']['rss_bytes'] > report['cost_stop']['rss_bytes']:
            raise RuntimeError('Load memory ceiling')
        rows = source_rows()
        for index in range(0, len(cases), 2):
            if compute >= 600:
                report['status'] = 'compute_budget_stop'; break
            batch = cases[index:index+2]
            log(dict(event='begin', case_ids=[c['case_id'] for c in batch], started_at=time.time()))
            begin = time.perf_counter()
            vectors = model.encode([c['query'] for c in batch], batch_size=2, normalize_embeddings=True,
                show_progress_bar=False, device='cpu')
            elapsed = time.perf_counter() - begin; compute += elapsed; report['query_encodings'] += len(batch)
            completed = []
            for c, vector in zip(batch, vectors):
                begin = time.perf_counter()
                found = search_vector_index(cpu.VECTOR_DB, list(map(float, vector)), max_order=c['max_order'], limit=10)
                search_ms = (time.perf_counter()-begin)*1000; compute += search_ms/1000
                ids = cpu.safe_ids([u for u,_ in found], c['max_order'], rows)
                completed.append(dict(case_id=c['case_id'], max_order=c['max_order'], query_sha256=hashlib.sha256(c['query'].encode()).hexdigest(),
                    candidate_units=ids, scores=[s for _,s in found], search_ms=search_ms))
                report['scope_searches'] += 1
            memory = cpu.memory_stats()
            info = dict(event='end', case_ids=[c['case_id'] for c in batch], encode_ms=elapsed*1000, cases=completed, memory=memory)
            log(info); report['cases'].extend(completed); report['batches'].append(info)
            print(f"New CPU Dense {len(report['cases'])}/18; batch {elapsed:.2f}s", flush=True)
            if memory['rss_bytes'] > report['cost_stop']['rss_bytes'] or compute >= 600:
                report['status'] = 'compute_or_memory_stop'; break
        else:
            report['status'] = 'complete'
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        log(dict(event='failure', error_type=type(exc).__name__, error=str(exc)))
    report.update(compute_seconds=compute, wall_seconds=time.perf_counter()-start, memory=cpu.memory_stats(),
        cuda_initialized=torch.cuda.is_initialized(), ended_at_unix=time.time(),
        incomplete_cases=[c['case_id'] for c in cases if c['case_id'] not in {r['case_id'] for r in report['cases']}])
    if report['cuda_initialized']: raise RuntimeError('CUDA initialized')
    return report


def summarize_split(reports, new_ids):
    return dict(new_story=cpu.summarize([r for r in reports if r['case_id'] in new_ids])['prospective'],
        old_story=cpu.summarize([r for r in reports if r['case_id'] not in new_ids])['prospective'],
        development=cpu.summarize(reports)['development'], stage=cpu.summarize(reports)['stage'], negative=cpu.summarize(reports)['negative'])


def alternatives_complete(case, ids):
    return any(set(s).issubset(ids) for s in case.get('acceptable_evidence_sets', [case['required_units']]))


def routes(dense_path):
    base = json.loads(dense_path.read_text(encoding='utf-8'))
    if (base['source_sha256'] != cpu.digest(cpu.SOURCE)
            or base['contract_sha256'] != canonical(json.loads(audit.CONTRACT.read_text(encoding='utf-8')))):
        raise ValueError('Expanded Dense provenance changed')
    existing = json.loads(audit.CACHE.read_text(encoding='utf-8'))
    if existing['source_sha256'] != base['source_sha256']: raise ValueError('Old cache source changed')
    cases = new_cases(); new_ids = {c['case_id'] for c in cases}; case_map = {c['case_id']:c for c in cpu.cases()+cases}
    dense_map = {r['case_id']:r for r in base['cases']}
    sys.path.insert(0,str(cpu.PIPELINE)); sys.path.insert(0,str(cpu.CHATBOT_SRC))
    from storymemory.adapter import StoryMemory
    from storypal_chatbot.story_memory import PipelineStoryMemoryBackend, StoryMemoryService
    from storypal_chatbot.context_packer import ContextPacker
    from .sparse import JiebaFtsAdapter
    init=time.perf_counter(); sparse=JiebaFtsAdapter('or'); sparse_init=(time.perf_counter()-init)*1000
    memory=StoryMemory(cpu.DATA,retrieval='fts'); strict=cpu.StrictFtsAdapter(memory)
    service=StoryMemoryService(PipelineStoryMemoryBackend(data_root=cpu.DATA,pipeline_code_path=cpu.PIPELINE,retrieval='fts'))
    packer=ContextPacker(); rows=source_rows(); evidence=source_evidence()
    configs={k:[dict(r,ranking_origin='old_cache_reused') for r in v['cases']] for k,v in existing['configurations'].items()}
    for c in cases:
        if c['case_id'] not in dense_map: continue
        d=dense_map[c['case_id']]; values={'dense':(d['candidate_units'],dict(search_ms=d['search_ms']))}
        if d['query_sha256'] != hashlib.sha256(c['query'].encode()).hexdigest() or d['max_order'] != c['max_order']:
            raise ValueError('Dense query or scope changed')
        for name,adapter in (('jieba_or',sparse),('fts_strict',strict),('fts_actual',memory)):
            started=time.perf_counter(); found=adapter.search('wandering_earth',c['query'],max_order=c['max_order'],top_k=10)
            values[name]=([r['unit_id'] for r in found],dict(search_ms=(time.perf_counter()-started)*1000,diagnostics=adapter.last_search_diagnostics))
        started=time.perf_counter(); ids,info=cpu.structure(c['query'],c['max_order'],rows,lambda q:_tokens(q,sparse.jieba),service)
        values['structure']=(ids,dict(info,search_ms=(time.perf_counter()-started)*1000))
        started=time.perf_counter(); ranked=rank_candidates(d['candidate_units'],values['jieba_or'][0],'rrf_dense2_sparse1')
        values['rrf_dense2_sparse1']=([r['unit_id'] for r in ranked],dict(fusion_ms=(time.perf_counter()-started)*1000))
        for name,(ids,info) in values.items():
            r=cpu.evaluate(c,ids,rows,memory,packer)
            r.update(acceptable_joint_at_10=alternatives_complete(c,ids),acceptable_packed_joint=alternatives_complete(c,r['packed_units']))
            configs[name].append(dict(r,**info,ranking_origin='new_computation'))
    packs={}
    for route,rankings in configs.items():
        for k in (5,10):
            for mode in audit.MODES:
                out=[]
                for r in rankings:
                    c=case_map[r['case_id']]; ids=r['candidate_units'][:k]; started=time.perf_counter()
                    selected,tokens,drops=audit.select(ids,evidence,c['query'],mode,packer,lambda text:terms(text,sparse.jieba))
                    cpu.safe_ids(selected,c['max_order'],rows)
                    if len(selected)>4 or tokens>2400: raise ValueError('Pack budget violation')
                    valid=r['eligible_for_full_set_diagnostic']
                    out.append(dict(case_id=c['case_id'],task_id=c['task_id'],set=c['set'],group=c['group'],max_order=c['max_order'],
                        eligible=valid,packed_units=selected,tokens=tokens,packed_joint=set(c['required_units']).issubset(selected) if valid else None,
                        acceptable_packed_joint=alternatives_complete(c,selected) if valid else None,drops=drops,
                        packing_ms=(time.perf_counter()-started)*1000,
                        separator_only=[u for u in selected if not any(ch.isalnum() for ch in evidence[u]['raw_text'])],
                        raw_duplicates_selected=len(selected)!=len({audit.raw_key(evidence[u]) for u in selected})))
                packs[f'{route}/top{k}/{mode}']=dict(new_story=audit.packing_metrics([r for r in out if r['case_id'] in new_ids])['prospective'],
                    old_story=audit.packing_metrics([r for r in out if r['case_id'] not in new_ids])['prospective'],
                    development=audit.packing_metrics(out)['development'],cases=out)
    if any(n in sys.modules for n in ('torch','transformers','sentence_transformers','openai')):
        raise RuntimeError('Routes unexpectedly loaded model or provider')
    return dict(schema='expanded-cpu-routes@1',source_sha256=base['source_sha256'],contract_sha256=base['contract_sha256'],
        dense_artifact_sha256=cpu.digest(dense_path),old_cache_sha256=cpu.digest(audit.CACHE),new_case_count=len(dense_map),
        sparse_init_ms=sparse_init,configurations={k:dict(summary=summarize_split(v,new_ids),cases=v) for k,v in configs.items()},
        pack_configurations=packs,new_provider_requests=0,new_reranker_pairs=0,memory=cpu.memory_stats(),real_agent_navigation=False,formal_new_gold=0)


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('phase',choices=('dense','routes')); p.add_argument('--input',type=Path); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); output=a.output.resolve()
    if not output.is_relative_to(cpu.RUNTIME.resolve()) or output.exists() or output.with_suffix('.progress.jsonl').exists():
        p.error('Use new isolated output and progress files')
    before=cpu.digest(cpu.LEDGER); started=time.perf_counter()
    result=dense(output) if a.phase=='dense' else routes(a.input)
    if cpu.digest(cpu.LEDGER)!=before: raise RuntimeError('Provider ledger changed')
    result.update(unchanged_previous_request_ledger_sha256=before,phase_wall_seconds=time.perf_counter()-started)
    with output.open('x',encoding='utf-8') as stream: json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps(dict(phase=a.phase,status=result.get('status','complete'),output=str(output))))


if __name__=='__main__': main()