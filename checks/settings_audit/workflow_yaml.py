"""Parse workflow YAML without silently accepting duplicate mapping keys."""


def load_unique_keys(yaml, text):
    """Keep BaseLoader's string semantics and reject duplicates at every depth."""
    class UniqueKeyLoader(yaml.BaseLoader):
        def construct_mapping(self, node, deep=False):
            mapping = super().construct_mapping(node, deep=deep)
            if len(mapping) != len(node.value):
                raise yaml.constructor.ConstructorError(
                    None, None, "duplicate mapping key", node.start_mark)
            return mapping

    # BaseLoader keeps GitHub's 'on' key and scalar values as strings.
    return yaml.load(text, Loader=UniqueKeyLoader)
