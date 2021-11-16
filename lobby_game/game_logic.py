import logging
import time
from typing import List, Optional

import attr

from lobby_game import tag_data
from nametag import protocol

FLAVOR_START = {"A": "TWIN", "B": "MAN", "C": "MOTHER"}

FLAVOR_END = {"A": "REST", "B": "IN", "C": "PEACE"}

NEXT_WORD = {
    # "Beheading" (Ichabod): Remove the first letter
    1: {
        w: w[1:]
        for w in {
            "AGO",
            "AWAY",
            "AWRY",
            "BOTHER",
            "LEAST",
            "MAN",
            "MOTHER",
            "OPEN",
            "SAGE",
            "SHUT",
            "SWAY",
            "TWIN",
            "TWIT",
            "WOMEN",
            "WON",
            "YEAST",
        }
    },
    # Letter edit (Eddie)
    2: {
        k: v
        for a, b in [
            ("AGE", "AGO"),
            ("AWAY", "AWRY"),
            ("COME", "HOME"),
            ("EAST", "MAST"),
            ("FATHER", "RATHER"),
            ("GO", "SO"),
            ("HUT", "OUT"),
            ("LEAST", "LEASH"),
            ("LOSE", "NOSE"),
            ("LOST", "MOST"),
            ("MAN", "MAP"),
            ("MEN", "MET"),
            ("MOTHER", "MOSHER"),
            ("OFF", "OAF"),
            ("OMEN", "OPEN"),
            ("ON", "AN"),
            ("OTHER", "OCHER"),
            ("PEN", "PUN"),
            ("SAME", "SAGE"),
            ("SHUT", "SMUT"),
            ("TWIN", "TWIT"),
            ("WAY", "WAR"),
            ("WEST", "REST"),
            ("WIN", "WON"),
            ("WIT", "WIG"),
            ("WOMAN", "WOMEN"),
            ("WRY", "WHY"),
        ]
        for k, v in ((a, b), (b, a))  # bidirectional
    },
    # Opposite (Jekyll)
    3: {
        k: v
        for a, b in [
            ("EAST", "WEST"),
            ("GO", "COME"),
            ("HOME", "AWAY"),
            ("MAN", "WOMAN"),
            ("MEN", "WOMEN"),
            ("MOST", "LEAST"),
            ("MOTHER", "FATHER"),
            ("ON", "OFF"),
            ("OPEN", "SHUT"),
            ("OTHER", "SAME"),
            ("OUT", "IN"),
            ("PEN", "PENCIL"),
            ("WAR", "PEACE"),
            ("WIN", "LOSE"),
            ("WON", "LOST"),
        ]
        for k, v in ((a, b), (b, a))  # bidirectional
    },
}

CHECKPOINT = {
    "SO": "GO",
    "COME": "GO",
    "HOME": "GO",
    "AWAY": "GO",
    "AWRY": "GO",
    "SWAY": "GO",
    "WAY": "GO",
    "WHY": "GO",
    "WRY": "GO",
    "WAR": "GO",
}

NEXT_GHOST = {
    "TWIN": 1,
    "MAN": 3,
    "MOTHER": 1,
    "GO": 3,
}


# Anagrams and opposites are reversible
for reversible in NEXT_WORD[2], NEXT_WORD[3]:
    for a, b in list(reversible.items()):
        reversible[b] = a


def program_for_tag(
    ghost_id: int,
    config: tag_data.TagConfig,
    stash: Optional[protocol.StashState],
) -> Optional[tag_data.DisplayProgram]:
    Scene = tag_data.DisplayScene
    State = tag_data.TagState

    start_word = FLAVOR_START.get(config.flavor, "BADTAG")
    end_word = FLAVOR_END.get(config.flavor, "BADTAG")

    from_backup = stash.from_backup if stash else False
    state = State.from_bytes(stash.data) if stash else None

    if not ghost_id:  # Staff station
        if state and state.phase in (b"GAM", b"WIN") and not from_backup:
            phase = state.phase.decode(errors="replace")
            logging.info(f'{config} Phase "{phase}" -> No change at staff')
            return None

        return tag_data.DisplayProgram(
            new_state=State(b"GAM", string=start_word.encode()),
            scenes=[
                Scene(f"need-tag{config.flavor}", end_word, bold=True),
                Scene("use-guides"),
                Scene("give", f'"{start_word}"', bold=True, blink=True),
            ],
        )

    if not state:
        return tag_data.DisplayProgram(
            new_state=State(b"RST"),
            scenes=[Scene("tag-reset")],
        )

    if state.phase != b"GAM":
        phase = state.phase.decode(errors="replace")
        logging.info(f'{config} Phase "{phase}" -> No change (non-GAM)')
        return None

    # TODO: Insert a "restored from backup" scene

    last_word = state.string.decode(errors="replace")
    last_ghost = state.number
    log_prefix = f'{config} G{last_ghost} "{last_word}" :: G{ghost_id}'

    if last_ghost == ghost_id:
        if stash and stash.from_backup:
            logging.info(f'{log_prefix} -> "{last_word}" (backup refresh)')
            return tag_data.DisplayProgram(
                new_state=state,
                scenes=[
                    Scene(
                        f"give-ghost{ghost_id}",
                        f'"{last_word}"',
                        bold=True,
                        blink=True,
                    )
                ],
            )
        else:
            logging.info(f"{log_prefix} -> No change (same station)")
            return None

    next_word = NEXT_WORD.get(ghost_id, {}).get(last_word)
    if next_word == end_word:
        logging.info(f'{log_prefix} => "{next_word}" success!!!')
        return tag_data.DisplayProgram(
            new_state=State(b"WIN"),
            scenes=[
                Scene(f"accept-ghost{ghost_id}", f'"{last_word}"'),
                Scene("success", f'"{next_word}"', bold=True, blink=True),
            ],
        )

    if next_word:
        logging.info(f'{log_prefix} => "{next_word}" advance')
        return tag_data.DisplayProgram(
            new_state=State(b"GAM", number=ghost_id, string=next_word.encode()),
            scenes=[
                Scene(f"accept-ghost{ghost_id}", f'"{last_word}"'),
                Scene(
                    f"give-ghost{ghost_id}",
                    f'"{next_word}"',
                    bold=True,
                    blink=True,
                ),
            ],
        )

    restart = CHECKPOINT.get(last_word, start_word)
    if last_word == restart:
        logging.info(f'{log_prefix} X> "{restart}" retry')
        return tag_data.DisplayProgram(
            new_state=State(b"GAM", number=ghost_id, string=restart.encode()),
            scenes=[
                Scene(f"reject-ghost{ghost_id}", f'"{last_word}"'),
                Scene("maybe-try-another"),
            ],
        )

    if ghost_id == NEXT_GHOST.get(restart, 0):
        skip = NEXT_WORD[ghost_id][restart]
        logging.info(f'{log_prefix} X> "{restart}" >> "{skip}" reskip')
        return tag_data.DisplayProgram(
            new_state=State(b"GAM", number=ghost_id, string=skip.encode()),
            scenes=[
                Scene(f"reject-ghost{ghost_id}", f'"{last_word}"'),
                Scene("was-back-at", f'"{restart}"'),
                Scene(f"accept-ghost{ghost_id}", f'"{restart}"'),
                Scene(
                    f"give-ghost{ghost_id}",
                    f'"{skip}"',
                    bold=True,
                    blink=True,
                ),
            ],
        )

    logging.info(f'{log_prefix} X> "{restart}" restart')
    new_state = State(b"GAM", number=ghost_id, string=restart.encode())
    return tag_data.DisplayProgram(
        new_state=new_state,
        scenes=[
            Scene(f"reject-ghost{ghost_id}", f'"{last_word}"'),
            Scene("now-back-at", f'"{restart}"', bold=True, blink=True),
            Scene("now-visit-another"),
        ],
    )


if __name__ == "__main__":
    import argparse

    from lobby_game import render_game
    from nametag import logging_setup, protocol

    parser = argparse.ArgumentParser()
    parser.add_argument("--ghost_id", type=int, default=1)
    parser.add_argument("--tag_flavor", default="A")
    parser.add_argument("--old_phase", default="GAM")
    parser.add_argument("--old_ghost", type=int, default=0)
    parser.add_argument("--old_word", default="LEAST")
    parser.add_argument("--save_image", default="tmp.gif")
    parser.add_argument("--stash_backup", type=bool, default=False)
    parser.add_argument("--stash_displaced", type=bool, default=False)
    parser.add_argument("--stash_age", type=float, default=0)
    parser.add_argument("--zoom", type=int, default=15)
    args = parser.parse_args()

    tag = tag_data.TagConfig(id="XXXX", flavor=args.tag_flavor)

    state = tag_data.TagState(
        phase=args.old_phase.encode(),
        number=args.old_ghost,
        string=args.old_word.encode(),
    )

    stash = protocol.StashState(
        data=bytes(state),
        from_backup=args.stash_backup,
        known_displaced=args.stash_displaced,
        backup_monotime=time.monotonic() - args.stash_age,
    )

    print(
        f"Tag: ghost={args.ghost_id} flavor=[{tag.flavor}] "
        f"state=[{state.phase.decode()} ghost={state.number} "
        f'word="{state.string.decode()}"]'
    )

    program = program_for_tag(ghost_id=args.ghost_id, config=tag, stash=stash)
    if not program:
        print("=> No display program!")
    else:
        print(f"=> {len(program.scenes)} scenes:")
        for scene in program.scenes:
            print(
                f'   [{scene.image_name}] "{scene.text}"'
                f"{' +bold' if scene.bold else ''}"
                f"{' +blink' if scene.blink else ''}"
            )

        render_game.render_to_file(
            program=program, path=args.save_image, zoom=args.zoom
        )
        print(f"Wrote image: {args.save_image}")
