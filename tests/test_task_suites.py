from sift.harness import load_tasks


def test_dev_help_archetype_suite_has_train_and_heldout_objective_tasks():
    tasks = load_tasks("tasks/dev_help_archetypes.json")

    assert len(tasks) >= 30
    assert len({task.id for task in tasks}) == len(tasks)
    assert {task.split for task in tasks} == {"train", "heldout"}
    assert all("objective-check" in task.tags for task in tasks)
