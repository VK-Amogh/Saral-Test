import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../models/conversation.dart';

class HistoryState {
  final List<Conversation> conversations;
  final String? activeConversationId;
  final String searchQuery;
  final bool isLoading;

  const HistoryState({
    this.conversations = const [],
    this.activeConversationId,
    this.searchQuery = '',
    this.isLoading = false,
  });

  HistoryState copyWith({
    List<Conversation>? conversations,
    String? activeConversationId,
    String? searchQuery,
    bool? isLoading,
  }) {
    return HistoryState(
      conversations: conversations ?? this.conversations,
      activeConversationId: activeConversationId ?? this.activeConversationId,
      searchQuery: searchQuery ?? this.searchQuery,
      isLoading: isLoading ?? this.isLoading,
    );
  }

  Map<String, List<Conversation>> get groupedConversations {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final yesterday = today.subtract(const Duration(days: 1));

    final filtered = conversations.where((c) {
      if (searchQuery.trim().isEmpty) return true;
      return c.title.toLowerCase().contains(searchQuery.toLowerCase().trim());
    }).toList();

    final Map<String, List<Conversation>> groups = {
      'Today': [],
      'Yesterday': [],
      'Older': [],
    };

    for (final convo in filtered) {
      final convoDate = DateTime(
        convo.updatedAt.year,
        convo.updatedAt.month,
        convo.updatedAt.day,
      );

      if (convoDate.isAtSameMomentAs(today)) {
        groups['Today']!.add(convo);
      } else if (convoDate.isAtSameMomentAs(yesterday)) {
        groups['Yesterday']!.add(convo);
      } else {
        groups['Older']!.add(convo);
      }
    }

    return groups;
  }
}

class HistoryNotifier extends Notifier<HistoryState> {
  @override
  HistoryState build() {
    // Provide initial conversations for rich UX out of the box
    final now = DateTime.now();
    final initialList = [
      Conversation(
        id: '1',
        title: 'Download Masked e-Aadhaar',
        createdAt: now.subtract(const Duration(minutes: 30)),
        updatedAt: now.subtract(const Duration(minutes: 30)),
      ),
      Conversation(
        id: '2',
        title: 'Check PVC Card Dispatch Status',
        createdAt: now.subtract(const Duration(days: 1, hours: 2)),
        updatedAt: now.subtract(const Duration(days: 1, hours: 2)),
      ),
      Conversation(
        id: '3',
        title: 'Find Nearest Aadhaar Seva Kendra',
        createdAt: now.subtract(const Duration(days: 4)),
        updatedAt: now.subtract(const Duration(days: 4)),
      ),
    ];

    Future.microtask(() => loadFromSupabase());

    return HistoryState(
      conversations: initialList,
      activeConversationId: initialList.first.id,
    );
  }

  Future<void> loadFromSupabase() async {
    try {
      final client = Supabase.instance.client;
      final userId = client.auth.currentUser?.id;
      if (userId == null) return;

      final response = await client
          .from('conversations')
          .select()
          .eq('user_id', userId)
          .eq('archived', false)
          .order('updated_at', ascending: false);

      final list = (response as List)
          .map((data) => Conversation.fromMap(data as Map<String, dynamic>))
          .toList();

      if (list.isNotEmpty) {
        state = state.copyWith(conversations: list);
      }
    } catch (_) {
      // In offline/test environments, preserve current state
    }
  }

  void setSearchQuery(String query) {
    state = state.copyWith(searchQuery: query);
  }

  void selectConversation(String id) {
    state = state.copyWith(activeConversationId: id);
  }

  Future<void> createConversation(String title) async {
    final newId = DateTime.now().millisecondsSinceEpoch.toString();
    final newConvo = Conversation(
      id: newId,
      title: title,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
    );

    state = state.copyWith(
      conversations: [newConvo, ...state.conversations],
      activeConversationId: newId,
    );

    try {
      final client = Supabase.instance.client;
      final userId = client.auth.currentUser?.id;
      if (userId != null) {
        await client.from('conversations').insert({
          'id': newId,
          'user_id': userId,
          'title': title,
        });
      }
    } catch (_) {}
  }

  Future<void> deleteConversation(String id) async {
    state = state.copyWith(
      conversations: state.conversations.where((c) => c.id != id).toList(),
      activeConversationId:
          state.activeConversationId == id ? null : state.activeConversationId,
    );

    try {
      final client = Supabase.instance.client;
      await client.from('conversations').delete().eq('id', id);
    } catch (_) {}
  }
}

final historyProvider =
    NotifierProvider<HistoryNotifier, HistoryState>(() => HistoryNotifier());
