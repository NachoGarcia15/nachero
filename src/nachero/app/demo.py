"""Draft ranked simulado (5v5) para ver el panel sin estar en una partida."""

import time


class Demo:
    """Simula un draft ranked completo 5v5. Tu eres el segundo pick azul (jungla)."""

    STEP_SECONDS = 4

    def __init__(self, champs):
        self.c, self.t0, self.locked = champs, time.time(), None

    def session(self, my_best):
        def i(name):
            return self.c.id(name) or 0

        step = int((time.time() - self.t0) / self.STEP_SECONDS) % 7
        if step < 5:
            self.locked = None
        elif self.locked is None:
            self.locked = my_best
        my_best = self.locked or my_best
        roles = ["top", "jungle", "middle", "bottom", "utility"]
        ally_final = [i("Darius"), 0, i("Zed"), i("Jinx"), i("Nautilus")]
        enemy_final = [i("Aatrox"), i("Viego"), i("Talon"), i("Kai'Sa"), i("Leona")]
        ally_bans = [i("Yone"), 0, i("Kayn"), i("Draven"), i("Pyke")]
        enemy_bans = [i("Graves"), i("Qiyana"), i("Akali"), i("Ezreal"), i("Blitzcrank")]
        pick_order = [[0], [5, 6], [1, 2], [7, 8], [3, 4], [9]]  # celdas que eligen en cada turno
        done_turns = {0: 0, 1: 0, 2: 0, 3: 1, 4: 2, 5: 4, 6: 6}[step]
        bans_done = step >= 2
        my_locked = step >= 5
        me_champ = my_best if my_locked else 0
        picked = {c for t in pick_order[:done_turns] for c in t}
        active = set(pick_order[done_turns]) if (bans_done and done_turns < 6) else set()

        my_team = []
        for k in range(5):
            cid = (me_champ if k == 1 else ally_final[k]) if k in picked or (k == 1 and my_locked) else 0
            intent = ally_final[k] if (k != 1 and k not in picked) else 0
            my_team.append({"cellId": k, "assignedPosition": roles[k], "championId": cid, "championPickIntent": intent})
        their = [{"cellId": 5 + k, "championId": enemy_final[k] if 5 + k in picked else 0} for k in range(5)]
        acts, aid = [], 0
        bans = []
        for k in range(10):
            aid += 1
            ally = k < 5
            champ = (ally_bans[k] if ally else enemy_bans[k - 5]) if bans_done else 0
            bans.append(
                {
                    "id": aid,
                    "actorCellId": k,
                    "type": "ban",
                    "isAllyAction": ally,
                    "completed": bans_done,
                    "isInProgress": (step == 1),
                    "championId": champ,
                }
            )
        acts.append(bans)
        for turn in pick_order:
            grp = []
            for cell in turn:
                aid += 1
                done = cell in picked or (cell == 1 and my_locked)
                champ = (
                    (me_champ if cell == 1 else (ally_final[cell] if cell < 5 else enemy_final[cell - 5]))
                    if done
                    else 0
                )
                grp.append(
                    {
                        "id": aid,
                        "actorCellId": cell,
                        "type": "pick",
                        "isAllyAction": cell < 5,
                        "completed": done,
                        "isInProgress": cell in active and not done,
                        "championId": champ,
                    }
                )
            acts.append(grp)
        phase = "PLANNING" if step == 0 else ("FINALIZATION" if step == 6 else "BAN_PICK")
        left = [28, 25, 27, 22, 18, 26, 40][step]
        return {
            "localPlayerCellId": 1,
            "myTeam": my_team,
            "theirTeam": their,
            "actions": acts,
            "bans": {"myTeamBans": [], "theirTeamBans": []},
            "timer": {"phase": phase, "adjustedTimeLeftInPhase": left * 1000},
        }, step
