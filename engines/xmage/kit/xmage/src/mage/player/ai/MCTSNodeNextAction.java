// Vendored from XMage fd40ad5c (MIT, see engines/xmage/NOTICE). Kit changes are marked KIT; the diff is published in kit/diffs/.
package mage.player.ai;

import mage.game.Game;

import java.util.List;

public interface MCTSNodeNextAction {
    List<MCTSNode> performNextAction(MCTSNode node, MCTSPlayer player, Game game, String fullStateValue);
}
