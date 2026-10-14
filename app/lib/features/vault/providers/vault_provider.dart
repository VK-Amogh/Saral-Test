import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../models/vault_document.dart';

class VaultState {
  final List<VaultDocument> documents;
  final bool isLoading;
  final String? errorMessage;

  const VaultState({
    this.documents = const [],
    this.isLoading = false,
    this.errorMessage,
  });

  VaultState copyWith({
    List<VaultDocument>? documents,
    bool? isLoading,
    String? errorMessage,
  }) {
    return VaultState(
      documents: documents ?? this.documents,
      isLoading: isLoading ?? this.isLoading,
      errorMessage: errorMessage,
    );
  }
}

class VaultNotifier extends Notifier<VaultState> {
  Timer? _countdownTimer;

  @override
  VaultState build() {
    final now = DateTime.now();
    // Default initial verified document for immediate UX
    final initialDocs = [
      VaultDocument(
        id: 'doc-001',
        docType: 'eaadhaar',
        fileName: 'eaadhaar_masked.pdf',
        storagePath: '/data/user/0/com.saralai/app_flutter/eaadhaar_masked.pdf',
        sizeBytes: 428400, // ~418 KB
        sha256: '9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08',
        pdfEncrypted: true,
        createdAt: now.subtract(const Duration(hours: 2)),
        deleteAfter: now.add(const Duration(hours: 22, minutes: 45)),
      ),
      VaultDocument(
        id: 'doc-002',
        docType: 'acknowledgement',
        fileName: 'update_request_receipt.pdf',
        storagePath: '/data/user/0/com.saralai/app_flutter/update_request_receipt.pdf',
        sizeBytes: 154200,
        sha256: '5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8',
        pdfEncrypted: false,
        createdAt: now.subtract(const Duration(hours: 6)),
        deleteAfter: now.add(const Duration(hours: 18, minutes: 12)),
      ),
    ];

    _startAutoDeleteTicker();
    Future.microtask(() => loadFromSupabase());

    ref.onDispose(() {
      _countdownTimer?.cancel();
    });

    return VaultState(documents: initialDocs);
  }

  void _startAutoDeleteTicker() {
    _countdownTimer?.cancel();
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      // Re-trigger tick to update remaining time counters
      final active = state.documents.where((d) => !d.isExpired).toList();
      if (active.length != state.documents.length) {
        state = state.copyWith(documents: active);
      } else {
        // Trigger UI rebuild for timers
        state = state.copyWith(documents: List.of(state.documents));
      }
    });
  }

  Future<void> loadFromSupabase() async {
    try {
      final client = Supabase.instance.client;
      final userId = client.auth.currentUser?.id;
      if (userId == null) return;

      final response = await client
          .from('documents')
          .select()
          .eq('user_id', userId)
          .order('created_at', ascending: false);

      final list = (response as List)
          .map((d) => VaultDocument.fromMap(d as Map<String, dynamic>))
          .toList();

      if (list.isNotEmpty) {
        state = state.copyWith(documents: list);
      }
    } catch (_) {
      // Offline fallback
    }
  }

  Future<void> deleteDocument(String id) async {
    state = state.copyWith(
      documents: state.documents.where((doc) => doc.id != id).toList(),
    );

    try {
      final client = Supabase.instance.client;
      await client.from('documents').delete().eq('id', id);
    } catch (_) {}
  }

  void addDocument(VaultDocument doc) {
    state = state.copyWith(documents: [doc, ...state.documents]);
  }
}

final vaultProvider =
    NotifierProvider<VaultNotifier, VaultState>(() => VaultNotifier());
