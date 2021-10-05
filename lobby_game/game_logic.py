import logging
from typing import List, Optional

import attr

import lobby_game.tag_data

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


# Anagrams and opposites are reversible
for reversible in NEXT_WORD[2], NEXT_WORD[3]:
    for a, b in list(reversible.items()):
        reversible[b] = a


def content_for_tag(
    ghost_id: int,
    config: lobby_game.tag_data.TagConfig,
    state: Optional[lobby_game.tag_data.TagState],
) -> Optional[lobby_game.tag_data.DisplayContent]:
    word = FLAVOR_START.get(config.flavor, "BADTAG")
    ghost_action = ""
    ghost_text = ""
    status_image = "title-start"
    status_text = f'"{word}"'

    if not state:
        logging.info(f'{config} No state >> G{ghost_id} "{word}" reset')
        ghost_action = "say"
        ghost_text = "RESET?"

    elif state.phase != b"GAM":
        phase = state.phase.decode(errors="replace")
        logging.info(f'{config} Phase "{phase}" >> G{ghost_id} "{word}" start')
        ghost_action = "say"
        ghost_text = "HELLO"

    else:
        last_word = state.string.decode(errors="replace")
        last_ghost = state.number
        log_prefix = f'{config} G{last_ghost} "{last_word}"'
        if last_ghost == ghost_id:
            logging.info(f"{log_prefix} -> G{ghost_id} No change (revisit)")
            return None

        if last_word in SUCCESS_WORDS:
            logging.info(f"{log_prefix} -> G{ghost_id} No change (success)")
            return None

        ghost_text = last_word
        next_word = NEXT_WORD.get(ghost_id, {}).get(last_word)
        if not next_word:
            logging.info(f'{log_prefix} X> G{ghost_id} "{word}" restart')
            ghost_action = "reject"
            status_image = "title-restart"

        else:
            word = next_word
            status_text = f'"{word}"'

            if word in SUCCESS_WORDS:
                logging.info(f'{log_prefix} => G{ghost_id} "{next_word}" !!!')
                ghost_action = ""
                status_image = "title-success"
            else:
                logging.info(f'{log_prefix} => G{ghost_id} "{next_word}" next')
                ghost_action = "accept"
                status_image = "title-next"

    content = lobby_game.tag_data.DisplayContent(
        new_state=lobby_game.tag_data.TagState(
            phase=b"GAM", number=ghost_id, string=word.encode()
        ),
        scenes=[],
    )

    if ghost_id and ghost_action:
        ghost_image = f"ghost-{ghost_id}-{ghost_action}"
        ghost_scene = lobby_game.tag_data.DisplayScene(ghost_image, ghost_text)
        content.scenes.append(ghost_scene)

    content.scenes.append(
        lobby_game.tag_data.DisplayScene(
            status_image, status_text, bold=True, blink=True
        )
    )
    return content


if __name__ == "__main__":
    import argparse

    import lobby_game.render_game
    import nametag.logging_setup

    parser = argparse.ArgumentParser()
    parser.add_argument("--ghost_id", type=int, default=1)
    parser.add_argument("--tag_flavor", default="A")
    parser.add_argument("--old_phase", default="GAM")
    parser.add_argument("--old_ghost", type=int, default=0)
    parser.add_argument("--old_word", default="LEAST")
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
        print(f"=> {len(content.scenes)} scenes:")
        for scene in content.scenes:
            print(
                f'   [{scene.image_name}] "{scene.text}"'
                f"{' +bold' if scene.bold else ''}"
                f"{' +blink' if scene.blink else ''}"
            )

        print()
        print("Rendering:")
        count = 0
        for scene in content.scenes:
            count += len(lobby_game.render_game.scene_frames(scene))

        print(f"=> {count} frames total")
