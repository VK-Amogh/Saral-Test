import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/theme/tokens.dart';
import '../models/conversation.dart';
import '../providers/history_provider.dart';

class HistoryDrawer extends ConsumerStatefulWidget {
  final Function(Conversation conversation)? onSelectConversation;
  final VoidCallback? onNewChat;

  const HistoryDrawer({
    super.key,
    this.onSelectConversation,
    this.onNewChat,
  });

  @override
  ConsumerState<HistoryDrawer> createState() => _HistoryDrawerState();
}

class _HistoryDrawerState extends ConsumerState<HistoryDrawer> {
  final TextEditingController _searchController = TextEditingController();

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  void _onSearchChanged(String query) {
    ref.read(historyProvider.notifier).setSearchQuery(query);
  }

  void _handleDelete(String id, String title) {
    showDialog(
      context: context,
      builder: (dialogCtx) => AlertDialog(
        backgroundColor: AppColors.darkGrey,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadii.card),
          side: const BorderSide(color: AppColors.borderWhite, width: 1.0),
        ),
        title: Text(
          'Delete Conversation',
          style: AppTypography.cardHeading(color: AppColors.pureWhite),
        ),
        content: Text(
          'Are you sure you want to permanently delete "$title"?',
          style: AppTypography.bodyMedium(color: AppColors.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogCtx).pop(),
            child: Text(
              'Cancel',
              style: AppTypography.labelMedium(color: AppColors.textSecondary),
            ),
          ),
          TextButton(
            onPressed: () {
              ref.read(historyProvider.notifier).deleteConversation(id);
              Navigator.of(dialogCtx).pop();
            },
            child: Text(
              'Delete',
              style: AppTypography.labelMedium(
                color: AppColors.pureWhite,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final historyState = ref.watch(historyProvider);
    final grouped = historyState.groupedConversations;

    return Drawer(
      backgroundColor: AppColors.pitchBlack,
      surfaceTintColor: Colors.transparent,
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Drawer Header
            Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.screenMargin,
                vertical: AppSpacing.space16,
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      'Conversations',
                      style: AppTypography.sectionHeading(),
                    ),
                  ),
                  // New Chat Icon Button
                  IconButton(
                    icon: const Icon(Icons.add_comment_outlined, color: AppColors.pureWhite),
                    tooltip: 'New Chat',
                    onPressed: () {
                      Navigator.of(context).pop();
                      widget.onNewChat?.call();
                    },
                  ),
                ],
              ),
            ),

            // Search pill input
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.screenMargin),
              child: TextField(
                controller: _searchController,
                onChanged: _onSearchChanged,
                style: AppTypography.bodyMedium(color: AppColors.pureWhite),
                decoration: InputDecoration(
                  hintText: 'Search chats...',
                  prefixIcon: const Icon(Icons.search, color: AppColors.textSecondary, size: 20),
                  suffixIcon: _searchController.text.isNotEmpty
                      ? IconButton(
                          icon: const Icon(Icons.close, color: AppColors.textSecondary, size: 18),
                          onPressed: () {
                            _searchController.clear();
                            _onSearchChanged('');
                          },
                        )
                      : null,
                  filled: true,
                  fillColor: AppColors.darkGrey,
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.space16,
                    vertical: AppSpacing.space8,
                  ),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(AppRadii.pill),
                    borderSide: const BorderSide(color: AppColors.borderWhite, width: 1.0),
                  ),
                ),
              ),
            ),

            const SizedBox(height: AppSpacing.space16),

            // Grouped Conversation Lists
            Expanded(
              child: ListView(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.screenMargin),
                children: [
                  if (grouped['Today']!.isNotEmpty)
                    _buildSection('Today', grouped['Today']!, historyState.activeConversationId),
                  if (grouped['Yesterday']!.isNotEmpty)
                    _buildSection('Yesterday', grouped['Yesterday']!, historyState.activeConversationId),
                  if (grouped['Older']!.isNotEmpty)
                    _buildSection('Older', grouped['Older']!, historyState.activeConversationId),
                  if (grouped['Today']!.isEmpty &&
                      grouped['Yesterday']!.isEmpty &&
                      grouped['Older']!.isEmpty)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: AppSpacing.space32),
                      child: Center(
                        child: Text(
                          'No conversations found',
                          style: AppTypography.bodyMedium(color: AppColors.textTertiary),
                        ),
                      ),
                    ),
                ],
              ),
            ),

            // Footer info
            Container(
              padding: const EdgeInsets.all(AppSpacing.space16),
              decoration: const BoxDecoration(
                border: Border(
                  top: BorderSide(color: AppColors.borderWhite, width: 1.0),
                ),
              ),
              child: Row(
                children: [
                  const Icon(Icons.shield_outlined, size: 16, color: AppColors.textTertiary),
                  const SizedBox(width: AppSpacing.space8),
                  Expanded(
                    child: Text(
                      'PII automatically scrubbed from history',
                      style: AppTypography.labelSmall(color: AppColors.textTertiary),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSection(String title, List<Conversation> items, String? activeId) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.space8),
          child: Text(
            title,
            style: AppTypography.dayHeader(color: AppColors.textSecondary),
          ),
        ),
        ...items.map((convo) => _buildConversationItem(convo, convo.id == activeId)),
        const SizedBox(height: AppSpacing.space8),
      ],
    );
  }

  Widget _buildConversationItem(Conversation convo, bool isActive) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: AppSpacing.space4),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(AppRadii.button),
        border: Border.all(
          color: isActive ? AppColors.pureWhite : AppColors.borderWhite,
          width: 1.0,
        ),
      ),
      child: Material(
        color: isActive ? AppColors.highlightSelected : AppColors.darkGrey,
        borderRadius: BorderRadius.circular(AppRadii.button),
        child: InkWell(
          borderRadius: BorderRadius.circular(AppRadii.button),
          onTap: () {
            ref.read(historyProvider.notifier).selectConversation(convo.id);
            Navigator.of(context).pop();
            widget.onSelectConversation?.call(convo);
          },
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.space12,
              vertical: AppSpacing.space8,
            ),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    convo.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTypography.bodyMedium(
                      color: isActive ? AppColors.pureWhite : AppColors.textPrimary,
                      fontWeight: isActive ? FontWeight.w600 : FontWeight.w400,
                    ),
                  ),
                ),
                IconButton(
                  icon: const Icon(Icons.delete_outline, color: AppColors.textTertiary, size: 18),
                  tooltip: 'Delete',
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(),
                  onPressed: () => _handleDelete(convo.id, convo.title),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
