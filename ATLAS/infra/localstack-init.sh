#!/bin/sh
awslocal sqs create-queue --queue-name atlas-tickets-dlq.fifo --attributes FifoQueue=true
awslocal sqs create-queue --queue-name atlas-tickets.fifo --attributes '{"FifoQueue":"true","ContentBasedDeduplication":"false","VisibilityTimeout":"360","RedrivePolicy":"{\"deadLetterTargetArn\":\"arn:aws:sqs:eu-central-1:000000000000:atlas-tickets-dlq.fifo\",\"maxReceiveCount\":\"3\"}"}'
