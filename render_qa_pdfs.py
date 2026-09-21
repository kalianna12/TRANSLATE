from pathlib import Path

import fitz


pairs = [
    (Path(r"G:\VSCODE_Save_Files\TRANSLATE\.qa_pages\after2.pdf"), Path(r"G:\VSCODE_Save_Files\TRANSLATE\.qa_pages\after2_png")),
    (Path(r"G:\VSCODE_Save_Files\TRANSLATE\.qa_pages\template.pdf"), Path(r"G:\VSCODE_Save_Files\TRANSLATE\.qa_pages\template_png")),
]

for pdf_path, output_dir in pairs:
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    for index, page in enumerate(doc):
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        pixmap.save(output_dir / f"page-{index + 1}.png")
    print(f"{pdf_path.name}: {len(doc)} pages")
