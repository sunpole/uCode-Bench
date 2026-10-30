"""Tiny offline PDF smoke for the actual frozen executable.

Runs only when --smoke is explicitly invoked; never touches user jobs.
No performance benchmark, camera test or GUI integration is implied.
"""
import hashlib
import json
from pathlib import Path
import tempfile


def main(root):
    from .batch import run_batch
    from .execution import ExecutionOptions
    from .print_settings import PrintSettings
    from . import __version__

    home=Path(root).resolve()
    home.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ucode-package-smoke-',dir=home) as folder:
        test_root=Path(folder)
        source=test_root/'codes.txt'
        source.write_text('200000000000\n200000000001\n',encoding='utf-8')
        job=run_batch(
            source, test_root/'jobs', mode='multipage',
            settings=PrintSettings(), execution=ExecutionOptions('serial',1,32),
            qa_mode='vector', activity='minimal')
        manifest=json.loads((job/'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('status')!='LIMITED':
            raise RuntimeError('Smoke QA must be LIMITED (vector-only), got '+str(manifest.get('status')))
        if manifest.get('count')!=2:
            raise RuntimeError('Smoke output must contain exactly two QR pages')
        pdfs=list(job.glob('*.pdf'))
        if len(pdfs)!=1:
            raise RuntimeError('Smoke must create exactly one combined PDF')
        pdf=pdfs[0]
        if pdf.stat().st_size<1000 or not pdf.read_bytes().startswith(b'%PDF-'):
            raise RuntimeError('Smoke output is not a plausible PDF file')
        print(json.dumps({
            'version':__version__, 'status':'PASS',
            'qa_mode':'vector', 'quality_status':manifest['status'],
            'pages':manifest['count'],
            'pdf_bytes':pdf.stat().st_size,
            'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),
            'runtime':'frozen-package-smoke'
        },ensure_ascii=False))
        return 0


if __name__=='__main__':
    from .distribution import user_root
    raise SystemExit(main(user_root()))
