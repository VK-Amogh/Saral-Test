"""
Saral AI — Mock Portal PDF Generator
File: mock_portal/pdf_generator.py

Generates valid encrypted/unencrypted test e-Aadhaar PDFs with %PDF- header
and %%EOF trailer, plus corrupt/html/oversize/malicious variants for failure testing.
"""

import io
from typing import Optional

try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


def generate_valid_pdf(
    encrypted: bool = True,
    password: str = "123456",
    size_kb: int = 15
) -> bytes:
    """Generate a valid compliant PDF document.

    Args:
        encrypted: If True, password-protect the PDF simulating e-Aadhaar encryption.
        password: The owner/user password for encryption.
        size_kb: Target approximate size in kilobytes (padded if needed).

    Returns:
        bytes: Binary content of a valid PDF starting with %PDF- and ending with %%EOF.
    """
    if PYPDF_AVAILABLE:
        writer = pypdf.PdfWriter()
        # Add a standard A4 page
        writer.add_blank_page(width=595.276, height=841.890)
        writer.add_metadata({
            "/Title": "Electronic Aadhaar Letter",
            "/Author": "Unique Identification Authority of India (UIDAI)",
            "/Subject": "e-Aadhaar Download Service",
            "/Creator": "Saral AI Mock Government Portal",
        })
        if encrypted:
            writer.encrypt(password)

        buf = io.BytesIO()
        writer.write(buf)
        data = buf.getvalue()
    else:
        # Fallback raw PDF 1.4 construction
        encrypt_dict = b"/Encrypt << /Filter /Standard >>" if encrypted else b""
        data = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
            + encrypt_dict + b"\n"
            b"xref\n0 4\n0000000000 65535 f \n0000000010 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
            b"trailer\n<< /Size 4 /Root 1 0 R " + (b"/Encrypt 4 0 R" if encrypted else b"") + b" >>\n"
            b"startxref\n210\n%%EOF\n"
        )

    # Pad to target size if requested
    target_bytes = size_kb * 1024
    if len(data) < target_bytes:
        # Prepend comment padding or trailer padding while preserving %PDF- and %%EOF
        padding_len = target_bytes - len(data) - 10
        if padding_len > 0:
            # Insert padding as a PDF comment right after header
            header_end = data.find(b"\n")
            if header_end != -1:
                header = data[:header_end + 1]
                rest = data[header_end + 1:]
                comment_padding = b"%" + (b" " * padding_len) + b"\n"
                data = header + comment_padding + rest

    return data


def generate_corrupt_pdf() -> bytes:
    """Generate corrupt PDF bytes with broken structure/xref for failure simulation."""
    return b"NOT_A_PDF_CORRUPT_DATA_STREAM_INVALID_XREF_AND_HEADER"


def generate_html_pdf() -> bytes:
    """Generate HTML text masquerading as PDF for failure simulation."""
    return b"<!DOCTYPE html><html><body><h1>500 Internal Server Error</h1><p>Portal unavailable.</p></body></html>"


def generate_oversize_pdf(size_mb: int = 6) -> bytes:
    """Generate a bloated PDF exceeding 5 MB limit.

    Args:
        size_mb: Size in megabytes (default: 6 MB, exceeding 5 MB limit).

    Returns:
        bytes: Oversize PDF payload.
    """
    header = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    trailer = b"\nxref\n0 2\n0000000000 65535 f \n0000000010 00000 n \ntrailer\n<< /Size 2 /Root 1 0 R >>\nstartxref\n60\n%%EOF\n"
    padding_needed = (size_mb * 1024 * 1024) - len(header) - len(trailer)
    padding = b"%" + (b"A" * max(padding_needed, 1024)) + b"\n"
    return header + padding + trailer


def generate_malicious_pdf(action_type: str = "javascript") -> bytes:
    """Generate a PDF containing forbidden /JavaScript or /Launch action dictionaries.

    Args:
        action_type: Either 'javascript' or 'launch'.

    Returns:
        bytes: PDF binary containing exploit signatures.
    """
    if action_type.lower() == "launch":
        action_dict = b"/OpenAction << /S /Launch /F (cmd.exe) >>"
    else:
        action_dict = (
            b"/Names << /JavaScript << /Names [(DocOpen) << /S /JavaScript /JS "
            b"(app.alert('malicious_execution')) >>] >> >>"
        )

    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R " + action_dict + b" >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000010 00000 n \n0000000095 00000 n \n0000000155 00000 n \n"
        b"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n230\n%%EOF\n"
    )


def build_test_pdf(
    encrypted: bool = True,
    malicious: Optional[str] = None,
    oversize: bool = False,
    corrupt: bool = False
) -> bytes:
    """Dispatcher matching conftest.py build_test_pdf signature for complete compatibility."""
    if corrupt:
        return generate_corrupt_pdf()
    if oversize:
        return generate_oversize_pdf(size_mb=6)
    if malicious:
        return generate_malicious_pdf(action_type=malicious)
    return generate_valid_pdf(encrypted=encrypted)
