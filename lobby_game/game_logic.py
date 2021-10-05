import logging
from typing import List, Optional

import attr

from lobby_game import tag_data

FLAVOR_START = {
    "A": "TWIN",
    "B": "MAN",
    "C": "MOTHER",
}

SUCCESS_WORDS = {
    "REST",
    "IN",
    "PEACE",
}

NEXT_WORD = {
    # "Beheading" (Ichabod): Remove the first letter
    1: {
        w: w[1:]
        for w in {
            "AGO",
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


# Anagrams and opposites are reversible
for reversible in NEXT_WORD[2], NEXT_WORD[3]:
    for a, b in list(reversible.items()):
        reversible[b] = a


def content_for_tag(
    ghost_id: int,
    config: tag_data.TagConfig,
    state: Optional[tag_data.TagState],
) -> Optional[tag_data.DisplayContent]:
    start_word = FLAVOR_START.get(config.flavor, "BADTAG")

    if not ghost_id:  # Staff station
        if state and (state.phase in (b"GAM", b"WIN")):
            phase = state.phase.decode(errors="replace")
            logging.info(f'{config} Phase "{phase}" -> No change at staff')
            return None

        return tag_data.DisplayContent(
            new_state=tag_data.TagState(b"GAM", string=start_word.encode()),
            scenes=[
                tag_data.DisplayScene(f"welcome1-{config.flavor}"),
                tag_data.DisplayScene("welcome2"),
                tag_data.DisplayScene("welcome3", f'"{start_word}"'),
            ],
        )

    if not state:
        return tag_data.DisplayContent(
            new_state=tag_data.TagState(b"RST"),
            scenes=[tag_data.DisplayScene("tag-reset")],
        )

    if state.phase != b"GAM":
        phase = state.phase.decode(errors="replace")
        logging.info(f'{config} Phase "{phase}" -> No change (non-GAM)')
        return None

    last_word = state.string.decode(errors="replace")
    last_ghost = state.number
    log_prefix = f'{config} G{last_ghost} "{last_word}" || G{ghost_id}'

    if last_ghost == ghost_id:
        logging.info(f"{log_prefix} -> No change (revisit)")
        return None

    next_word = NEXT_WORD.get(ghost_id, {}).get(last_word)
    if not next_word:
        checkpoint = CHECKPOINT.get(last_word)
        if checkpoint:
            logging.info(f'{log_prefix} X> "{checkpoint}" checkpoint')
            return tag_data.DisplayContent(
                new_state=tag_data.TagState(
                    b"GAM", number=ghost_id, string=checkpoint.encode()
                ),
                scenes=[
                    tag_data.DisplayScene("reject1-ghost{ghost_id}", last_word),
                    tag_data.DisplayScene(
                        "reject2-checkpoint",
                        f'"{checkpoint}"',
                        bold=True,
                        blink=True,
                    ),
                    tag_data.DisplayScene("reject3"),
                ],
            )

        logging.info(f'{log_prefix} X> "{start_word}" restart')
        return tag_data.DisplayContent(
            new_state=tag_data.TagState(
                b"GAM", number=ghost_id, string=start_word.encode()
            ),
            scenes=[
                tag_data.DisplayScene("reject1-ghost{ghost_id}", last_word),
                tag_data.DisplayScene(
                    "reject2", f'"{start_word}"', bold=True, blink=True
                ),
                tag_data.DisplayScene("reject3"),
            ],
        )

    if next_word in SUCCESS_WORDS:
        logging.info(f'{log_prefix} => "{next_word}" !!!')
        return tag_data.DisplayContent(
            new_state=tag_data.TagState(b"WIN"),
            scenes=[
                tag_data.DisplayScene("success1"),
                tag_data.DisplayScene(
                    "success2", f'"{next_word}"', bold=True, blink=True
                ),
            ],
        )

    logging.info(f'{log_prefix} => "{next_word}"')
    return tag_data.DisplayContent(
        new_state=tag_data.TagState(
            b"GAM", number=ghost_id, string=next_word.encode()
        ),
        scenes=[
            tag_data.DisplayScene(f"accept1-ghost{ghost_id}", last_word),
            tag_data.DisplayScene(
                "accept2", f'"{next_word}"', bold=True, blink=True
            ),
            tag_data.DisplayScene("accept3"),
        ],
    )


if __name__ == "__main__":
    import argparse

    import nametag.logging_setup

    parser = argparse.ArgumentParser()
    parser.add_argument("--ghost_id", type=int, default=1)
    parser.add_argument("--tag_flavor", default="A")
    parser.add_argument("--old_phase", default="GAM")
    parser.add_argument("--old_ghost", type=int, default=0)
    parser.add_argument("--old_word", default="LEAST")
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
