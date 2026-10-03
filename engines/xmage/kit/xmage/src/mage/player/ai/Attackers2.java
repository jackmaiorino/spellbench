// Vendored from XMage fd40ad5c (MIT, see engines/xmage/NOTICE). Kit changes are marked KIT; the diff is published in kit/diffs/.


package mage.player.ai;

import mage.game.permanent.Permanent;

import java.util.ArrayList;
import java.util.List;
import java.util.TreeMap;

/**
 *
 * @author BetaSteward_at_googlemail.com
 */
public class Attackers2 extends TreeMap<Integer, List<Permanent>> {

    public List<Permanent> getAttackers() {
        List<Permanent> attackers = new ArrayList<>();
        for (List<Permanent> l: this.values()) {
            for (Permanent permanent: l) {
                attackers.add(permanent);
            }
        }
        return attackers;
    }

}
