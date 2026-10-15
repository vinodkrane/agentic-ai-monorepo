from langchain_text_splitters import RecursiveCharacterTextSplitter

from app import config


def make_chunks(doc_id, source, pages, groups,
                chunk_size=config.CHUNK_SIZE, overlap=config.CHUNK_OVERLAP):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks = []
    idx = 0
    for page_no, text in pages:
        for piece in splitter.split_text(text):
            # very small fragments (page numbers, footers) just add noise
            if len(piece.strip()) < 30:
                continue
            chunks.append({
                "chunk_id": f"{doc_id}-{idx:04d}",
                "doc_id": doc_id,
                "source": source,
                "page": page_no,
                "chunk_index": idx,
                "text": piece,
                "allowed_groups": groups,
            })
            idx += 1
    return chunks
