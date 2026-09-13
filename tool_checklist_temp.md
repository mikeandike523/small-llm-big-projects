# Approval Mode Tool Checklist

Tools to focus on for `auto-accept-edits` / `full-auto` approval-mode logic.

## Always Approval-Gated Today

- [ ] `create_dir`
- [ ] `create_text_file`
- [ ] `write_text_file`
- [ ] `delete_file`
- [ ] `remove_dir`
- [ ] `copy_file`
- [ ] `copy_dir`
- [ ] `move_dir_or_file`
- [ ] `restore_file` (`restore` action; `list` is already allowed)
- [ ] `host_shell`
- [ ] `open_in_terminal`

## Path-Scoped Read / Navigation / Search

- [ ] `change_pwd`
- [ ] `find_files_by_name`
- [ ] `line_reader`
- [ ] `list_dir`
- [ ] `list_working_tree`
- [ ] `read_text_file`
- [ ] `search_filesystem_by_regex`

## Mixed / Special Approval Logic

- [ ] `text_editor`

## Notes

- `request_unredacted=True` remains centrally approval-gated regardless of tool mode.
- `snapshot_file` is currently approval-free but should be audited separately because it reads file contents into session snapshot storage.
