"""Local storage management for simulation jobs.

This modules provides the 'LocalStorage' class to create job directories
and store configuration, input data, and output files.

Constants:
    STORAGE_ROOT (Path): Root path for all job storage (default: "/data/storage").

Classes:
    LocalStorage: Provides methods to create directories and store job-related files.
"""

import os
from pathlib import Path
import shutil

from omegaconf import DictConfig

from backend.schemas.sim import SimInput, SimOutput

STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "/data/storage"))


class LocalStorage:
    """Class for managing job storage directories and files.

    Methods:
        mkdirs(job_id): Create directory structure for a job.
        store_config(job_id, payload): Store job configuration files.
        store_data(job_id, cfg): Store input data files for a job.
        store_output(job_id, result): Store simulation output files.
    """

    def mkdirs(job_id: int | str):
        """Create directory structure for a job.

        The directory structure includes:
            - jobs/<job_id>/
                - configs/
                - data/
                - output/

        Args:
            job_id (int or str): The unique ID of the job.
        """
        job_dir = STORAGE_ROOT / "jobs" / str(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "configs").mkdir(parents=True, exist_ok=True)
        (job_dir / "data").mkdir(parents=True, exist_ok=True)
        (job_dir / "output").mkdir(parents=True, exist_ok=True)

    def store_config(job_id: int | str, payload: SimInput):
        """Store the configuration files of a job.

        Copies the contents of the configuration directory specified in the
        payload to the job's 'configs' directory.

        Args:
            job_id (int or str): The unique ID of the job.
            payload (SimInput): The simulation input payload containing
                'config_dir' and 'config_name'.

        Returns:
            (tuple[str, str]): A tuple containing:
                - The path to the stored configuration directory.
                - The configuration file/directory name.
        """
        job_dir = STORAGE_ROOT / "jobs" / str(job_id)
        job_config_dir = job_dir / "configs"
        job_config_name = Path(payload["config_name"])
        shutil.copytree(str(Path(payload["config_dir"])), str(job_config_dir), dirs_exist_ok=True)
        return str(job_config_dir), str(job_config_name)
    
    def store_data(job_id: int | str, cfg: DictConfig):
        """Store input data files required for the job.

        Copies required data files (e.g., geography and station CSVs,
        incidents) to the job's 'data' directory.

        Args:
            job_id (int or str): The unique ID of the job.
            cfg (DictConfig): Configuration object containing paths to data
                files used in the simulation.

        Returns:
            (str): The path to the stored data directory.
        """
        job_dir = STORAGE_ROOT / "jobs" / str(job_id)
        job_data_dir = job_dir / "data"
        shutil.copy(Path(cfg.city.geography.bounds_geojson), str(job_data_dir))
        shutil.copy(Path(cfg.city.stations.csv_path), str(job_data_dir))
        shutil.copy(Path(cfg.demand.incidents_csv), str(job_data_dir))
        return str(job_data_dir)

    def store_output(job_id: int | str, result: SimOutput):
        """Store simulation output files for the job.

        Copies simulation result files to the job's 'output' directory.

        Args:
            job_id (int or str): The unique ID of the job.
            result (SimOutput): Object containing paths to simulation output
                files (incident report, apparatus events, step trace).

        Returns:
            (str): The path to the stored output directory.
        """
        job_dir = STORAGE_ROOT / "jobs" / str(job_id)
        job_output_dir = job_dir / "output"
        shutil.copy(result.path_incident_report, str(job_output_dir))
        shutil.copy(result.path_apparatus_events, str(job_output_dir))
        shutil.copy(result.path_step_trace, str(job_output_dir))
        return str(job_output_dir)
