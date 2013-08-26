from setuptools import setup, find_packages
setup(
    name = "chef-solo-provisioner",
    version = "0.1",
    packages = ( 'aminatorplugins', ),
    namespace_packages = ( 'aminatorplugins', ),

    # Project uses reStructuredText, so ensure that the docutils get
    # installed or upgraded on the target machine
    install_requires = [],

    package_data = { },

    # metadata for upload to PyPI
    author = "Asbjorn Kjaer",
    author_email = "bunjiboys@bunjiboys.dk",
    description = "Chef Solo provisioner for Netflix's aminator",
    license = "APACHE 2.0",
    keywords = "aminator plugin chef-solo chef solo",
)
