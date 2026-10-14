import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/chat_message.dart';

class ChatState {
  final List<ChatMessage> messages;
  final bool isStreaming;
  final String? activeTaskId;

  const ChatState({
    this.messages = const [],
    this.isStreaming = false,
    this.activeTaskId,
  });

  ChatState copyWith({
    List<ChatMessage>? messages,
    bool? isStreaming,
    String? activeTaskId,
  }) {
    return ChatState(
      messages: messages ?? this.messages,
      isStreaming: isStreaming ?? this.isStreaming,
      activeTaskId: activeTaskId ?? this.activeTaskId,
    );
  }
}

class ChatNotifier extends Notifier<ChatState> {
  StreamSubscription? _streamSubscription;
  bool _disposed = false;

  @override
  ChatState build() {
    _disposed = false;
    ref.onDispose(() {
      _disposed = true;
      _streamSubscription?.cancel();
    });

    return const ChatState(messages: []);
  }

  void startNewChat() {
    _streamSubscription?.cancel();
    state = const ChatState(messages: []);
  }

  Future<void> sendMessage(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return;

    final userMessage = ChatMessage(
      id: 'msg-${DateTime.now().millisecondsSinceEpoch}',
      role: 'user',
      content: trimmed,
      createdAt: DateTime.now(),
    );

    state = state.copyWith(
      messages: [...state.messages, userMessage],
      isStreaming: true,
    );

    // Check if message triggers task automation
    final isAadhaarDownload = trimmed.toLowerCase().contains('download') ||
        trimmed.toLowerCase().contains('aadhaar');

    if (isAadhaarDownload) {
      await _triggerAadhaarTask();
    } else {
      await _streamAssistantResponse(
        'I am your Saral AI assistant. You can ask me to download your masked e-Aadhaar, track PVC card delivery, verify updates, or locate the nearest Aadhaar Seva Kendra. All interactions are end-to-end encrypted and strictly confidential.',
      );
    }
  }

  Future<void> _triggerAadhaarTask() async {
    final taskId = 'task-${DateTime.now().millisecondsSinceEpoch.toString().substring(6)}';

    // Add inline task card message
    final taskMessage = ChatMessage(
      id: 'task-msg-${DateTime.now().millisecondsSinceEpoch}',
      role: 'task',
      content: 'Initiating Aadhaar automation workflow',
      taskId: taskId,
      createdAt: DateTime.now(),
    );

    state = state.copyWith(
      messages: [...state.messages, taskMessage],
      activeTaskId: taskId,
    );

    // Stream introductory assistant instruction
    await _streamAssistantResponse(
      'Starting UIDAI masked e-Aadhaar retrieval. Please review the live task progress above and prepare to provide verification credentials securely.',
    );
  }

  Future<void> _streamAssistantResponse(String fullText) async {
    final assistantMsgId = 'assistant-${DateTime.now().millisecondsSinceEpoch}';
    final initialAssistantMsg = ChatMessage(
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      createdAt: DateTime.now(),
      isStreaming: true,
    );

    state = state.copyWith(
      messages: [...state.messages, initialAssistantMsg],
      isStreaming: true,
    );

    // Simulate SSE token chunk streaming
    final words = fullText.split(' ');
    final buffer = StringBuffer();

    for (int i = 0; i < words.length; i++) {
      if (_disposed) break;
      await Future.delayed(const Duration(milliseconds: 30));
      if (_disposed) break;

      buffer.write(words[i]);
      if (i < words.length - 1) buffer.write(' ');

      final updatedMessages = state.messages.map((msg) {
        if (msg.id == assistantMsgId) {
          return msg.copyWith(
            content: buffer.toString(),
            isStreaming: i < words.length - 1,
          );
        }
        return msg;
      }).toList();

      state = state.copyWith(messages: updatedMessages);
    }

    if (!_disposed) {
      state = state.copyWith(isStreaming: false);
    }
  }
}

final chatProvider =
    NotifierProvider<ChatNotifier, ChatState>(() => ChatNotifier());
