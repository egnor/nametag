import logging
from typing import List, Optional

import attr

import lobby_game.tag_data
import nametag.protocol

FLAVOR_START = {
    "A": "PLEASE",
    "B": "TANGLE",
    "C": "NEARLY",
}

SUCCESS_WORDS = {
    "STRONG",
    "DIED",
    "LOVED",
}

NEXT_WORD = {
    # Beheading (Ichabod)
    1: {
        "ASLEEP": "SLEEP",
        "AWAKE": "WAKE",
        "DEVIL": "EVIL",
        "DRANK": "RANK",
        "LATE": "ATE",
        "LEASE": "EASE",
        "NEARLY": "EARLY",
        "PEELS": "EELS",
        "PLEASE": "LEASE",
        "TANGLE": "ANGLE",
    },
    # Anagram (Basil) -- inverses automatically added
    2: {
        "ANGLE": "ANGEL",
        "ANGST": "GNATS",
        "DEATH": "HATED",
        "DEVIL": "LIVED",
        "EVIL": "VILE",
        "FILE": "LIFE",
        "LATE": "TEAL",
        "LEASE": "EASEL",
        "PLEASE": "ASLEEP",
        "SLEEP": "PEELS",
        "WAKE": "WEAK",
    },
    # Opposite (Hyde) -- inverses automatically added
    3: {
        "ANGEL": "DEVIL",
        "ANGLE": "CURVE",
        "ASLEEP": "AWAKE",
        "ATE": "DRANK",
        "EARLY": "LATE",
        "EASE": "ANGST",
        "EVIL": "GOOD",
        "HATED": "LOVED",
        "LEASE": "BUY",
        "LIFE": "DEATH",
        "LIVED": "DIED",
        "NEARLY": "EXACT",
        "PEELS": "COVERS",
        "PLEASE": "ANNOY",
        "RANK": "FILE",
        "SLEEP": "WAKE",
        "TANGLE": "COMB",
        "TEAL": "MAROON",
        "WEAK": "STRONG",
    },
}


# Anagrams and opposites are reversible
for reversible in NEXT_WORD[2], NEXT_WORD[3]:
    for a, b in list(reversible.items()):
        reversible[b] = a


@attr.define
class DisplayContent:
    status_title: str
    status_text: str
    ghost_id: int = 0
    ghost_action: str = ""
    ghost_text: str = ""
    new_state: Optional[lobby_game.tag_data.TagState] = None


def content_for_tag(
    ghost_id: int,
    config: lobby_game.tag_data.TagConfig,
    state: Optional[lobby_game.tag_data.TagState],
) -> Optional[DisplayContent]:
    start = FLAVOR_START.get(config.flavor, "BADTAG")

    content = DisplayContent(
        ghost_id=ghost_id,
        status_title="start",
        status_text=f'"{start}"',
        new_state=lobby_game.tag_data.TagState(
            phase=b"GAM", number=ghost_id, string=start.encode()
        ),
    )

    if not state:
        logging.info(f'{config} No state >> G{ghost_id} "{start}" reset')
        return attr.evolve(content, ghost_action="say", ghost_text="RESET?")

    if state.phase != b"GAM":
        phase = state.phase.decode(errors="replace")
        logging.info(f'{config} Phase "{phase}" >> G{ghost_id} "{start}" start')
        return attr.evolve(content, ghost_action="say", ghost_text="HELLO")

    last_word = state.string.decode(errors="replace")
    last_ghost = state.number
    old_text = f'{config} G{last_ghost} "{last_word}"'
    if last_ghost == ghost_id:
        logging.info(f"{old_text} -> G{ghost_id} No change (revisit)")
        return None

    if last_word in SUCCESS_WORDS:
        logging.info(f"{old_text} -> G{ghost_id} No change (success)")
        return None

    content.ghost_text = f'"{last_word}"'
    next_word = NEXT_WORD.get(ghost_id, {}).get(last_word)
    if not next_word:
        logging.info(f'{old_text} X> G{ghost_id} "{start}" restart')
        return attr.evolve(
            content, ghost_action="reject", status_title="restart"
        )

    status_title = "success" if next_word in SUCCESS_WORDS else "next"
    logging.info(f'{old_text} => G{ghost_id} "{next_word}" {status_title}')
    return attr.evolve(
        content,
        ghost_action="accept",
        status_title=status_title,
        status_text=f'"{next_word}"',
        new_state=attr.evolve(content.new_state, string=next_word.encode()),
    )


if __name__ == "__main__":
    import argparse

    import lobby_game.render_game
    import nametag.logging_setup

    parser = argparse.ArgumentParser()
    parser.add_argument("--ghost_id", type=int, default=1)
    parser.add_argument("--tag_flavor", default="A")
    parser.add_argument("--old_phase", default="GAM")
    parser.add_argument("--old_ghost", type=int, default=0)
    parser.add_argument("--old_word", default="")
    args = parser.parse_args()

    tag = lobby_game.tag_data.TagConfig(id="XXXX", flavor=args.tag_flavor)

    state = lobby_game.tag_data.TagState(
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
        print(
            f"=> Display: ghost=[id={content.ghost_id} "
            f'action={content.ghost_action} word="{content.ghost_text}"] '
            f'title={content.status_title} word="{content.status_text}"'
        )

        steps = lobby_game.render_game.steps_for_content(content)
        print(f"=> {len(steps)} steps")
