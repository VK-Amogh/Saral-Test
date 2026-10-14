class ChatMessage {
  final String id;
  final String role; // 'user', 'assistant', 'task'
  final String content;
  final String? taskId;
  final DateTime createdAt;
  final bool isStreaming;

  const ChatMessage({
    required this.id,
    required this.role,
    required this.content,
    this.taskId,
    required this.createdAt,
    this.isStreaming = false,
  });

  ChatMessage copyWith({
    String? id,
    String? role,
    String? content,
    String? taskId,
    DateTime? createdAt,
    bool? isStreaming,
  }) {
    return ChatMessage(
      id: id ?? this.id,
      role: role ?? this.role,
      content: content ?? this.content,
      taskId: taskId ?? this.taskId,
      createdAt: createdAt ?? this.createdAt,
      isStreaming: isStreaming ?? this.isStreaming,
    );
  }
}
