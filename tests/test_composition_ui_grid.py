from music_create.composition.models import SUPPORTED_GRIDS
from music_create.ui.app import composition_grid_options


def test_composition_grid_options_match_supported_grid_order() -> None:
    assert composition_grid_options() == SUPPORTED_GRIDS
    assert len(composition_grid_options()) == 12
    assert composition_grid_options()[0] == "1"
    assert composition_grid_options()[-1] == "1/64"

