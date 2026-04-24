from typing import Any, TypeAlias

Path: TypeAlias = tuple[str, ...]


def web_search_filter(result_json: dict[str, Any]) -> dict[str, Any]:
    """
    Filter a web-search response by removing specific noisy or oversized fields.

    This function walks a nested JSON-like structure and removes a small set of
    hardcoded fields that are not useful for downstream display or inspection.

    Current rules:
    - Remove the top-level ``mixed`` object.
    - Remove any object under a ``thumbnail`` key.
    - Remove ``img`` values anywhere inside a ``profile`` subtree.
    - Remove ``favicon`` values anywhere inside a ``meta_url`` subtree.

    Traversal rules:
    - Dictionaries are traversed recursively.
    - Lists are traversed recursively only when every item in the list is a
      dictionary.
    - Other lists are treated as ordinary values and are filtered as a whole.

    Path semantics:
    - Paths are mostly key-based.
    - During traversal of a list of dictionaries, the original item index is
      appended to the path as a string.
    - Those indices are included only to make paths unique while recursing.
      They should not be treated as stable semantic identifiers, because after
      filtering, the final list size and element positions may have changed.

    Args:
        result_json: Parsed JSON object to filter.

    Returns:
        A filtered copy of the input object.

    Raises:
        ValueError: If the top-level object is removed entirely.
    """

    def is_list_of_dicts(value: Any) -> bool:
        """
        Return True if ``value`` is a list and every element is a dictionary.
        """
        return isinstance(value, list) and all(isinstance(item, dict) for item in value)

    def should_keep_value(path: Path, value: Any) -> bool:
        """
        Decide whether a non-recursively visited value should be kept.

        Args:
            path: Path to the value.
            value: Value at that path.

        Returns:
            True if the value should be kept, otherwise False.
        """
        del value  # Reserved for future value-based filtering rules.

        if "profile" in path and path[-1] == "img":
            return False

        if "meta_url" in path and path[-1] == "favicon":
            return False

        return True

    def should_keep_dict(path: Path, value: dict[str, Any]) -> bool:
        """
        Decide whether an entire dictionary object should be kept.

        Args:
            path: Path to the dictionary.
            value: Dictionary at that path.

        Returns:
            True if the dictionary should be kept, otherwise False.
        """
        del value  # Reserved for future dict-based filtering rules.

        if path == ("mixed",):
            return False

        if path and path[-1] == "thumbnail":
            return False

        if (
            len(path) > 1
            and (path[0] in ["web", "news", "faq", "discussions"])
            and path[1] == "results"
            and (path[-1] in ["meta_url", "profile"])
        ):
            return False

        return True

    def visit(obj: Any, path: Path) -> tuple[Any, bool]:
        """
        Recursively filter a JSON-like object.

        Returns:
            A pair ``(filtered_obj, keep_flag)`` where ``keep_flag`` indicates
            whether the object should remain in its parent container.
        """
        if isinstance(obj, dict):
            if not should_keep_dict(path, obj):
                return None, False

            filtered_dict: dict[str, Any] = {}

            for key, value in obj.items():
                child_path = path + (key,)

                if isinstance(value, dict) or is_list_of_dicts(value):
                    filtered_value, keep = visit(value, child_path)
                    if keep:
                        filtered_dict[key] = filtered_value
                elif should_keep_value(child_path, value):
                    filtered_dict[key] = value

            return filtered_dict, bool(filtered_dict)

        if is_list_of_dicts(obj):
            filtered_list: list[dict[str, Any]] = []

            for index, item in enumerate(obj):
                # The index recorded here is the original input position.
                filtered_item, keep = visit(item, path + (str(index),))
                if keep:
                    filtered_list.append(filtered_item)

            return filtered_list, bool(filtered_list)

        return obj, True

    filtered_result, keep = visit(result_json, ())

    if not keep or filtered_result is None:
        raise ValueError("Filter excluded top level object.")

    return filtered_result
