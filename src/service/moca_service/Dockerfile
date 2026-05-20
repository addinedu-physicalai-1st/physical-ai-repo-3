FROM ros:jazzy-ros-base

ENV PIP_BREAK_SYSTEM_PACKAGES=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3-pip python3-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /ros_ws
COPY service/moca_service/controller_status_msgs ./src/controller_status_msgs
RUN . /opt/ros/jazzy/setup.sh && colcon build --packages-select controller_status_msgs

WORKDIR /app
COPY service/moca_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY service/moca_service/app ./app

EXPOSE 9001

CMD ["/bin/bash", "-lc", "source /opt/ros/jazzy/setup.bash && source /ros_ws/install/setup.bash && python3 -m app.main"]
