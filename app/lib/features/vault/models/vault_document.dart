class VaultDocument {
  final String id;
  final String docType;
  final String fileName;
  final String storagePath;
  final int sizeBytes;
  final String sha256;
  final bool pdfEncrypted;
  final DateTime createdAt;
  final DateTime deleteAfter;

  const VaultDocument({
    required this.id,
    required this.docType,
    required this.fileName,
    required this.storagePath,
    required this.sizeBytes,
    required this.sha256,
    this.pdfEncrypted = true,
    required this.createdAt,
    required this.deleteAfter,
  });

  factory VaultDocument.fromMap(Map<String, dynamic> map) {
    return VaultDocument(
      id: map['id']?.toString() ?? '',
      docType: map['doc_type']?.toString() ?? 'document',
      fileName: map['file_name']?.toString() ?? 'file.pdf',
      storagePath: map['storage_path']?.toString() ?? '',
      sizeBytes: (map['size_bytes'] as num?)?.toInt() ?? 0,
      sha256: map['sha256']?.toString() ?? '',
      pdfEncrypted: map['pdf_encrypted'] as bool? ?? true,
      createdAt: map['created_at'] != null
          ? DateTime.tryParse(map['created_at'].toString()) ?? DateTime.now()
          : DateTime.now(),
      deleteAfter: map['delete_after'] != null
          ? DateTime.tryParse(map['delete_after'].toString()) ??
              DateTime.now().add(const Duration(hours: 24))
          : DateTime.now().add(const Duration(hours: 24)),
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'doc_type': docType,
      'file_name': fileName,
      'storage_path': storagePath,
      'size_bytes': sizeBytes,
      'sha256': sha256,
      'pdf_encrypted': pdfEncrypted,
      'created_at': createdAt.toIso8601String(),
      'delete_after': deleteAfter.toIso8601String(),
    };
  }

  Duration get remainingTime {
    final diff = deleteAfter.difference(DateTime.now());
    return diff.isNegative ? Duration.zero : diff;
  }

  bool get isExpired => remainingTime == Duration.zero;

  String get formattedSize {
    if (sizeBytes < 1024) return '$sizeBytes B';
    if (sizeBytes < 1024 * 1024) {
      return '${(sizeBytes / 1024).toStringAsFixed(1)} KB';
    }
    return '${(sizeBytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
}
