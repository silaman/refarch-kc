# Validate event sourcing pattern: create new orders to the order microservice end points
# validate the order is added and a order created event was added
# It assumes the event broker (kafka) and all the solution services are running locally (by default)
# If these tests have to run against remote deployed solution the following environment variables are used:
import unittest
import os
import json
import requests
import time

KAFKA_BROKERS=os.environ['KAFKA_BROKERS']
ORDER_CMD_MS=os.environ['ORDER_CMD_MS']

# listen to orders topic, verify orderCreated event was published
from confluent_kafka import Consumer, KafkaError, Producer

# See https://github.com/edenhill/librdkafka/blob/master/CONFIGURATION.md
orderConsumer = Consumer({
    'bootstrap.servers': KAFKA_BROKERS,
    'group.id': 'python-orders-consumer',
    'auto.offset.reset': 'earliest',
    'enable.auto.commit': True
})
orderConsumer.subscribe(['orders'])

def pollNextOrder(orderID):
    gotIt = False
    order = {}
    while not gotIt:
        msg = orderConsumer.poll(timeout=1.0)
        if msg is None:
            continue
        if msg.error():
            print("Consumer error: {}".format(msg.error()))
            continue
        print('%% %s [%d] at offset %d with key %s:\n' %
                                 (msg.topic(), msg.partition(), msg.offset(),
                                  str(msg.key())))
        orderStr = msg.value().decode('utf-8')
        print('Received message: {}'.format(orderStr))
        orderEvent = json.loads(orderStr)
        if (orderEvent['payload']['orderID'] == orderID):
            gotIt = True
    return orderEvent

def getAllOrderedOrderEvents(orderID):
    print("Get all event mathing the given orderID")
    orderReloader = Consumer({
    'bootstrap.servers': KAFKA_BROKERS,
    'group.id': 'python-orders-reload',
    'auto.offset.reset': 'earliest',
    'enable.auto.commit': False
    })
    orderReloader.subscribe(['orders'])
    orderEvents = []
    gotAll = False
    while not gotAll:
        msg = orderReloader.poll(timeout=30)
        if msg is None:
            print('Timed out... assume we have all')
            gotAll = True
            continue
        if msg.error():
            print("Consumer error: {}".format(msg.error()))
            continue
        eventAsString = msg.value().decode('utf-8')
        orderEvent = json.loads(eventAsString)
        if (orderEvent['payload']['orderID'] == orderID):
            orderEvents.append(orderEvent)
    orderReloader.close()
    return orderEvents

def delivery_report(err, msg):
    """ Called once for each message produced to indicate delivery result.
        Triggered by poll() or flush(). """
    if err is not None:
        print('Message delivery failed: {}'.format(err))
    else:
        print('Message delivered to {} [{}]'.format(msg.topic(), msg.partition()))

def postContainerAllocated(orderID):
    orderProducer = Producer({'bootstrap.servers': KAFKA_BROKERS})
    data = {"timestamp": int(time.time()),"type":"OrderContainerAllocated","version":"1","payload": {"containerID": "c10","orderID":orderID}}
    dataStr = json.dumps(data)
    orderProducer.produce('orders',dataStr.encode('utf-8'), callback=delivery_report)
    orderProducer.flush()


'''
Test the happy path for the state diagram as in 
https://ibm-cloud-architecture.github.io/refarch-kc/design/readme/#shipment-order-lifecycle-and-state-change-events
'''
class TestEventSourcingHappyPath(unittest.TestCase):
    def test_createOrder(self):
        # 1- load the order request from json
        f = open('../data/FreshProductOrder.json','r')
        order = json.load(f)
        f.close()
        # 2- create order by doing a POST on /api/orders of the orders command service
        res = requests.post("http://" + ORDER_CMD_MS + "/orders",json=order)
        orderID=json.loads(res.text)['orderID']
        self.assertIsNotNone(orderID)
        print(' Got an order created with ID ' + orderID)
        # 3- get OrderCreated Event
        orderEvent = pollNextOrder(orderID)
        self.assertEqual(orderEvent['type'], "OrderCreated")
        # 4- get next order event, should be assigned to a voyage
        orderEvent = pollNextOrder(orderID)
        self.assertEqual(orderEvent['type'], "OrderAssigned")
        voyage=orderEvent['payload']
        self.assertIsNotNone(voyage)
        self.assertIsNotNone(voyage['voyageID'])
        # 5- Simulate assignment of the container
        postContainerAllocated(orderID)
        # 6- list all events 
        orderEvents = getAllOrderedOrderEvents(orderID)
        for oe in orderEvents:
            print(oe)
       


if __name__ == '__main__':
    unittest.main()
    orderConsumer.close()