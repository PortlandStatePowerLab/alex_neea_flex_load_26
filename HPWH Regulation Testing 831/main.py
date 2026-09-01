import subprocess
import os
import sys
from pathlib import Path
from datetime import datetime
import shutil
import argparse

base_dir = Path(__file__).resolve().parent
project_dir = base_dir.parent
if str(project_dir) not in sys.path:
    sys.path.insert(0, str(project_dir))

OLD_BLDG_DIR = os.path.join(base_dir, "HPWH All Portland Input Files")



# get type of fl
# get parameters for fl
# get parameters for ochre
#   Population, adoption rate, start/stop time, timestep, dr participation?, % reachable?, path to reg sig or select rega or regd
# send parameters to A3
# run A3
# run B2
# run C1
# run C2
# run C3
# send correlation from c3 to excel


def main(del_bldg="N", reg_type="RegA"):

    # Choose the run ID once. RegA/RegD suffixes keep the two result sets apart.
    base_run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    import HPWH_B2 as run_ochre_base
    import HPWH_B3 as run_ochre_cntrl
    import HPWH_A3 as adj_xml
    all_pdx_path = Path(os.path.join(base_dir, "HPWH All Portland Input Files"))
    if not all_pdx_path.is_dir():
        adj_xml.main()
    regulation_label = {"RegA": "Slow", "RegD": "Fast"}[reg_type]
    run_id = f"{base_run_id}_{regulation_label}"
    base_result = run_ochre_base.main(run_id=run_id, reg_type=reg_type)

    up_cap = base_result["up_regulation_capacity_p90_kw"]
    dwn_cap = base_result["down_regulation_capacity_p90_kw"]

    run_ochre_cntrl.main(
        run_id=run_id,
        reg_type=reg_type,
        up_cap=up_cap,
        dwn_cap=dwn_cap,
    )
    subprocess.run([sys.executable, str(base_dir / "HPWH_C1.py"), "--run-id", run_id], check=True)
    # subprocess.run([sys.executable, str(project_dir / "HPWH" / "HPWH_C2.py"), "--run-id", run_id], check=True)
    subprocess.run([sys.executable, str(base_dir / "HPWH_C3.py"), "--run-id", run_id], check=True)
    # from HPWH import HPWH_C3_Plot_norm_pwr as get_reg
    # reg_corr = get_reg.main()
    import HPWH_C4 as pjm_scores
    pjm_score = pjm_scores.main(run_id)
    print(f"PJM Score ({regulation_label}): {pjm_score}")

    if del_bldg == "Y":
        if os.path.isdir(OLD_BLDG_DIR):
            shutil.rmtree(OLD_BLDG_DIR)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--del-bldg", 
        choices=("Y", "N"),
        default="N")
    parser.add_argument(
        "--reg-type",
        choices=("RegA", "RegD"),
        default="RegA",
        help="Regulation signal to use for this run (default: RegA).",
    )
    args = parser.parse_args()
    main(args.del_bldg, args.reg_type)
