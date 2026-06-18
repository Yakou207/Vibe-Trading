import unittest


class CheckEnvTest(unittest.TestCase):
    def test_collect_environment_status_reports_python_packages_and_project_files(self) -> None:
        from scripts.check_env import collect_environment_status

        status = collect_environment_status()

        self.assertIn("python", status)
        self.assertIn("packages", status)
        self.assertIn("project_files", status)
        self.assertIn("pandas", status["packages"])
        self.assertIn("outputs/strategy_comparison_report.json", status["project_files"])


if __name__ == "__main__":
    unittest.main()
