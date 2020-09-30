import setuptools


with open("requirements.txt") as fp:
    install_requires = fp.read().splitlines()

setuptools.setup(
    name="channelbot",
    packages=setuptools.find_packages(),
    install_requires=install_requires,
    include_package_data=True,
)
