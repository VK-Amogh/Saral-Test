import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/tokens.dart';
import '../../../core/widgets/glass_surface.dart';
import '../../auth/providers/auth_provider.dart';
import '../../history/presentation/history_drawer.dart';
import '../models/chat_message.dart';
import '../providers/chat_provider.dart';
import 'widgets/task_stepper_card.dart';

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final TextEditingController _composerController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();

  final List<String> _suggestionPills = [
    'Download Aadhaar',
    'Check Status',
    'Update Address',
    'Find Kendra',
  ];

  @override
  void dispose() {
    _composerController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: AppDurations.medium,
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _handleSend([String? presetText]) {
    final text = presetText ?? _composerController.text;
    if (text.trim().isEmpty) return;

    ref.read(chatProvider.notifier).sendMessage(text);
    if (presetText == null) {
      _composerController.clear();
    }
    _scrollToBottom();
  }

  void _handleVoiceInput() {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'Listening for voice query...',
          style: AppTypography.bodySmall(color: AppColors.pureWhite),
        ),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final chatState = ref.watch(chatProvider);
    final messages = chatState.messages;

    return Scaffold(
      key: _scaffoldKey,
      backgroundColor: AppColors.pitchBlack,
      drawer: HistoryDrawer(
        onSelectConversation: (convo) {
          ref.read(chatProvider.notifier).startNewChat();
          _handleSend(convo.title);
        },
        onNewChat: () {
          ref.read(chatProvider.notifier).startNewChat();
        },
      ),
      appBar: AppBar(
        backgroundColor: AppColors.pitchBlack,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.menu, color: AppColors.pureWhite),
          tooltip: 'Conversation History',
          onPressed: () => _scaffoldKey.currentState?.openDrawer(),
        ),
        title: Text(
          'Saral AI',
          style: AppTypography.sectionHeading(),
        ),
        centerTitle: true,
        actions: [
          IconButton(
            icon: const Icon(Icons.lock_clock_outlined, color: AppColors.pureWhite),
            tooltip: 'Document Vault',
            onPressed: () => context.push('/vault'),
          ),
          IconButton(
            icon: const Icon(Icons.logout, color: AppColors.textSecondary),
            tooltip: 'Sign Out',
            onPressed: () async {
              await ref.read(authProvider.notifier).signOut();
              if (context.mounted) {
                context.go('/auth');
              }
            },
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            // Chat messages or Greeting Empty State
            Expanded(
              child: messages.isEmpty
                  ? _buildEmptyStateGreeting()
                  : ListView.builder(
                      controller: _scrollController,
                      padding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.screenMargin,
                        vertical: AppSpacing.space16,
                      ),
                      itemCount: messages.length,
                      itemBuilder: (ctx, index) {
                        final msg = messages[index];
                        return _buildMessageItem(msg);
                      },
                    ),
            ),

            // Suggestion pills (when fewer than 3 messages)
            if (messages.length < 3) ...[
              _buildSuggestionPillsBar(),
              const SizedBox(height: AppSpacing.space8),
            ],

            // Rounded Composer Pill
            _buildComposerPill(chatState.isStreaming),

            const SizedBox(height: AppSpacing.space8),
          ],
        ),
      ),
    );
  }

  Widget _buildEmptyStateGreeting() {
    return SingleChildScrollView(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.screenMargin),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const SizedBox(height: AppSpacing.space48),

          // Arapey Greeting per rules.md
          Text(
            'Namaste',
            textAlign: TextAlign.center,
            style: AppTypography.screenTitle(),
          ),
          const SizedBox(height: AppSpacing.space12),
          Text(
            'How can I help you today?',
            textAlign: TextAlign.center,
            style: AppTypography.greeting(color: AppColors.textSecondary),
          ),
          const SizedBox(height: AppSpacing.space16),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.space24),
            child: Text(
              'Autonomous, privacy-first assistant for Indian civic and identity services.',
              textAlign: TextAlign.center,
              style: AppTypography.bodyMedium(color: AppColors.textTertiary),
            ),
          ),

          const SizedBox(height: AppSpacing.space40),

          // Feature Highlights Card
          GlassSurface(
            padding: const EdgeInsets.all(AppSpacing.space20),
            child: Column(
              children: [
                _buildFeatureRow(
                  Icons.badge_outlined,
                  'Masked e-Aadhaar',
                  'Download password-protected official PDF directly to vault',
                ),
                const Divider(color: AppColors.borderWhite, height: AppSpacing.space24),
                _buildFeatureRow(
                  Icons.verified_user_outlined,
                  'Zero Cloud Secrets',
                  'Aadhaar numbers and OTPs processed in-memory only',
                ),
                const Divider(color: AppColors.borderWhite, height: AppSpacing.space24),
                _buildFeatureRow(
                  Icons.timer_outlined,
                  'Auto-Purge Vault',
                  'Downloaded credentials automatically destroyed after retention',
                ),
              ],
            ),
          ),

          const SizedBox(height: AppSpacing.space32),
        ],
      ),
    );
  }

  Widget _buildFeatureRow(IconData icon, String title, String subtitle) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(
            color: AppColors.pitchBlack,
            shape: BoxShape.circle,
            border: Border.all(color: AppColors.borderWhite, width: 1.0),
          ),
          child: Icon(icon, color: AppColors.pureWhite, size: 18),
        ),
        const SizedBox(width: AppSpacing.space12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: AppTypography.labelLarge(color: AppColors.pureWhite),
              ),
              const SizedBox(height: 2),
              Text(
                subtitle,
                style: AppTypography.bodySmall(color: AppColors.textSecondary),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildSuggestionPillsBar() {
    return SizedBox(
      height: AppChrome.capsule + 8,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.screenMargin),
        itemCount: _suggestionPills.length,
        separatorBuilder: (context, index) => const SizedBox(width: AppSpacing.space8),
        itemBuilder: (ctx, index) {
          final pillText = _suggestionPills[index];
          return ActionChip(
            backgroundColor: AppColors.darkGrey,
            side: const BorderSide(color: AppColors.borderWhite, width: 1.0),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(AppRadii.pill),
            ),
            label: Text(
              pillText,
              style: AppTypography.labelSmall(
                color: AppColors.pureWhite,
                fontWeight: FontWeight.w500,
              ),
            ),
            onPressed: () => _handleSend(pillText),
          );
        },
      ),
    );
  }

  Widget _buildMessageItem(ChatMessage msg) {
    if (msg.role == 'task' && msg.taskId != null) {
      return TaskStepperCard(
        taskId: msg.taskId!,
        initialStatus: 'RUNNING',
        initialProgress: 25,
        onNavigateToVault: () => context.push('/vault'),
      );
    }

    final isUser = msg.role == 'user';

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: AppSpacing.space8),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.82,
        ),
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.space16,
          vertical: AppSpacing.space12,
        ),
        decoration: BoxDecoration(
          color: isUser ? AppColors.darkGrey : AppColors.graphite,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(AppRadii.card),
            topRight: const Radius.circular(AppRadii.card),
            bottomLeft: Radius.circular(isUser ? AppRadii.card : AppRadii.xs),
            bottomRight: Radius.circular(isUser ? AppRadii.xs : AppRadii.card),
          ),
          border: Border.all(
            color: isUser ? const Color(0x26FFFFFF) : AppColors.borderWhite,
            width: 1.0,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              msg.content,
              style: AppTypography.bodyMedium(
                color: isUser ? AppColors.pureWhite : AppColors.pureWhite,
              ),
            ),
            if (msg.isStreaming) ...[
              const SizedBox(height: 4),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 6,
                    height: 12,
                    color: AppColors.pureWhite,
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildComposerPill(bool isStreaming) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.screenMargin),
      child: Container(
        height: AppChrome.bar,
        padding: const EdgeInsets.only(
          left: AppSpacing.space16,
          right: AppSpacing.space4,
        ),
        decoration: BoxDecoration(
          color: AppColors.darkGrey,
          borderRadius: BorderRadius.circular(AppRadii.pill),
          border: Border.all(color: AppColors.borderWhite, width: 1.0),
        ),
        child: Row(
          children: [
            // Voice Microphone button
            IconButton(
              icon: const Icon(Icons.mic_none, color: AppColors.textSecondary, size: 22),
              tooltip: 'Voice Search',
              onPressed: _handleVoiceInput,
            ),

            // Input field
            Expanded(
              child: TextField(
                controller: _composerController,
                style: AppTypography.bodyMedium(color: AppColors.pureWhite),
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => _handleSend(),
                decoration: const InputDecoration(
                  hintText: 'Ask Saral anything...',
                  hintStyle: TextStyle(color: AppColors.textTertiary),
                  border: InputBorder.none,
                  enabledBorder: InputBorder.none,
                  focusedBorder: InputBorder.none,
                  contentPadding: EdgeInsets.symmetric(vertical: AppSpacing.space12),
                  filled: false,
                ),
              ),
            ),

            // Send Button Pill
            Container(
              width: AppChrome.compactCircle,
              height: AppChrome.compactCircle,
              decoration: const BoxDecoration(
                color: AppColors.pureWhite,
                shape: BoxShape.circle,
              ),
              child: IconButton(
                icon: const Icon(Icons.arrow_upward, color: AppColors.pitchBlack, size: 20),
                tooltip: 'Send',
                onPressed: isStreaming ? null : () => _handleSend(),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
