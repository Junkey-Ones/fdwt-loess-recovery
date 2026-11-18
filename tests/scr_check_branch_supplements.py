"""分支自身时点、发生/强度域和主表不变性的核验。"""
from copy import deepcopy
from src.M7.scr_branch_supplements import prepare_branch_views


def test_fz_uses_own_active_pentad_and_strict_dfai_does_not_filter_occurrence():
    events=[dict(episode_id=k,route1_A_eligible=True,route1_FR_eligible=True,F_R=False,
                 F_Z=flag,t_e=10,F_R_subtype=None) for k,flag in (("a",True),("b",True),("c",None))]
    original=deepcopy(events)
    branches=[dict(episode_id=k,branch="F_Z",t_w=t,E2a_eligible=False,DFAI=None)
              for k,t in (("a",11),("b",10))]
    trajectory=[dict(episode_id="a",t_abs=11,active_flag=False),dict(episode_id="b",t_abs=10,active_flag=True)]
    view,intensity,audit=prepare_branch_views(events,branches,trajectory)
    assert events==original
    assert view[0]["F_R"] is True and not view[0]["route1_FR_eligible"]
    assert view[1]["F_R"] is True and view[1]["route1_FR_eligible"]
    assert view[2]["F_R"] is None and view[2]["route1_FR_eligible"]
    assert not intensity["F_Z"] and audit["positive"]==1 and audit["unknown"]==1
