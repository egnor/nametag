import logging
from typing import List, Optional

import attr

from lobby_game import tag_data

FLAVOR_START = {"A": "TWIN", "B": "MAN", "C": "MOTHER"}

FLAVOR_END = {"A": "REST", "B": "IN", "C": "PEACE"}

NEXT_WORD = {
    # "Beheading" (Ichabod): Remove the first letter
    1: {
        w: w[1:]
        for w in {
            "AGO",
            "AWAY",
            "BOTHER",
            "LEAST",
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
            ("AWAY", "SWAY"),
            ("COME", "HOME"),
            ("EAST", "MAST"),
            ("FATHER", "RATHER"),
            ("GO", "SO"),
            ("HUT", "OUT"),
            ("LEAST", "YEAST"),
            ("LOSE", "NOSE"),
            ("LOST", "MOST"),
            ("MAN", "MEN"),
            ("MOTHER", "BOTHER"),
            ("OMEN", "OPEN"),
            ("OTHER", "OCHER"),
            ("PEN", "PUN"),
            ("SAME", "SAGE"),
            ("SHUT", "SHUN"),
            ("TWIN", "TWIT"),
            ("WAY", "WAR"),
            ("WEST", "REST"),
            ("WIN", "WON"),
            ("WIT", "WIG"),
            ("WOMAN", "WOMEN"),
        ]
        for k, v in ((a, b), (b, a))  # bidirectional
    },
    # Opposite (Hyde) -- inverses automatically added
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
    "SWAY": "GO",
    "WAY": "GO",
    "WAR": "GO",
}

NEXT_GHOST = {
    "TWIN": 1,
    "MAN": 2,
    "MOTHER": 1,
    "GO": 3,
}


# Anagrams and opposites are reversible
for reversible in NEXT_WORD[2], NEXT_WORD[3]:
    for a, b in list(reversible.items()):
        reversible[b] = a


def content_for_tag(
    ghost_id: int,
    config: tag_data.TagConfig,
    state: Optional[tag_data.TagState],
) -> Optional[tag_data.DisplayContent]:
    Scene = tag_data.DisplayScene
    State = tag_data.TagState

    start_word = FLAVOR_START.get(config.flavor, "BADTAG")
    end_word = FLAVOR_END.get(config.flavor, "BADTAG")

    if not ghost_id:  # Staff station
        if state and (state.phase in (b"GAM", b"WIN")):
            phase = state.phase.decode(errors="replace")
            logging.info(f'{config} Phase "{phase}" -> No change at staff')
            return None

        return tag_data.DisplayContent(
            new_state=State(b"GAM", string=start_word.encode()),
            scenes=[
                Scene(f"need-tag{config.flavor}", end_word, bold=True),
                Scene("use-guides"),
                Scene("give", f'"{start_word}"', bold=True, blink=True),
            ],
        )

    if not state:
        return tag_data.DisplayContent(
            new_state=State(b"RST"),
            scenes=[Scene("tag-reset")],
        )

    if state.phase != b"GAM":
        phase = state.phase.decode(errors="replace")
        logging.info(f'{config} Phase "{phase}" -> No change (non-GAM)')
        return None

    last_word = state.string.decode(errors="replace")
    last_ghost = state.number
    log_prefix = f'{config} G{last_ghost} "{last_word}" :: G{ghost_id}'

    if last_ghost == ghost_id:
        logging.info(f"{log_prefix} -> No change (revisit)")
        return None

    next_word = NEXT_WORD.get(ghost_id, {}).get(last_word)
    if next_word == end_word:
        logging.info(f'{log_prefix} => "{next_word}" success!!!')
        return tag_data.DisplayContent(
            new_state=State(b"WIN"),
            scenes=[
                Scene(f"accept-ghost{ghost_id}", f'"{last_word}"'),
                Scene("success", f'"{next_word}"', bold=True, blink=True),
            ],
        )

    if next_word:
        logging.info(f'{log_prefix} => "{next_word}" advance')
        return tag_data.DisplayContent(
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
        return tag_data.DisplayContent(
            new_state=State(b"GAM", number=ghost_id, string=restart.encode()),
            scenes=[
                Scene(f"reject-ghost{ghost_id}", f'"{last_word}"'),
                Scene("maybe-try-another"),
            ],
        )

    if ghost_id == NEXT_GHOST.get(restart, 0):
        skip = NEXT_WORD[ghost_id][restart]
        logging.info(f'{log_prefix} X> "{restart}" >> "{skip}" reskip')
        return tag_data.DisplayContent(
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
    return tag_data.DisplayContent(
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
    from nametag import logging_setup

    parser = argparse.ArgumentParser()
    parser.add_argument("--ghost_id", type=int, default=1)
    parser.add_argument("--tag_flavor", default="A")
    parser.add_argument("--old_phase", default="GAM")
    parser.add_argument("--old_ghost", type=int, default=0)
    parser.add_argument("--old_word", default="LEAST")
    parser.add_argument("--save_image", default="tmp.gif")
    parser.add_argument("--zoom", type=int, default=15)
    args = parser.parse_args()

    tag = tag_data.TagConfig(id="XXXX", flavor=args.tag_flavor)

    state = tag_data.TagState(
        phase=args.old_phase.encode(),
        number=args.old_ghost,
        string=args.old_word.encode(),
    )

    print(
        f"Tag: ghost={args.ghost_id} flavor=[{tag.flavor}] "
        f"state=[{state.phase.decode()} ghost={state.number} "
        f'word="{state.string.decode()}"]'
    )

    content = content_for_tag(ghost_id=args.ghost_id, config=tag, state=state)
    if not content:
        print("=> No display!")
    else:
        print(f"=> {len(content.scenes)} scenes:")
        for scene in content.scenes:
            print(
                f'   [{scene.image_name}] "{scene.text}"'
                f"{' +bold' if scene.bold else ''}"
                f"{' +blink' if scene.blink else ''}"
            )

        render_game.render_to_file(
            content=content, path=args.save_image, zoom=args.zoom
        )
        print(f"Wrote image: {args.save_image}")
