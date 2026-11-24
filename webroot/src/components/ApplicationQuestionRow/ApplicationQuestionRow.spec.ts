//
//  ApplicationQuestionRow.spec.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import { expect } from 'chai';
import { mountFull, mountShallow } from '@tests/helpers/setup';
import ApplicationQuestionRow from '@components/ApplicationQuestionRow/ApplicationQuestionRow.vue';
import { FormInput } from '@models/FormInput/FormInput.model';
import Joi from 'joi';

const createFormInput = (validation = Joi.boolean().required()) => new FormInput({
    id: 'question-group',
    name: 'question',
    label: 'Is this a question?',
    shouldHideLabel: true,
    value: null,
    valueOptions: [
        { value: true, name: 'Yes' },
        { value: false, name: 'No' },
    ],
    validation,
});

describe('ApplicationQuestionRow component', async () => {
    it('should mount the component', async () => {
        const wrapper = await mountShallow(ApplicationQuestionRow, { props: { formInput: createFormInput() }});

        expect(wrapper.exists()).to.equal(true);
        expect(wrapper.findComponent(ApplicationQuestionRow).exists()).to.equal(true);
    });
    it('should render the question text as the label for horizontal yes / no radios', async () => {
        const wrapper = await mountFull(ApplicationQuestionRow, { props: { formInput: createFormInput() }});

        expect(wrapper.find('.question-text').attributes('id')).to.equal('question');
        expect(wrapper.find('.question-text').text()).to.equal('Is this a question?*');
        expect(wrapper.find('[role="radiogroup"]').attributes('aria-labelledby')).to.equal('question');
        expect(wrapper.find('.radio-button-group-container').classes()).to.include('is-horizontal');
        expect(wrapper.findAll('input[type="radio"]').length).to.equal(2);
        expect(wrapper.find('.question-row').classes()).to.not.include('is-stacked');
    });
    it('should support stacking the radios under the question text', async () => {
        const wrapper = await mountFull(ApplicationQuestionRow, {
            props: { formInput: createFormInput(), isStacked: true },
        });

        expect(wrapper.find('.question-row').classes()).to.include('is-stacked');
    });
    it('should hide the required indicator for optional questions', async () => {
        const wrapper = await mountFull(ApplicationQuestionRow, {
            props: { formInput: createFormInput(Joi.boolean().allow(null)) },
        });

        expect(wrapper.find('.question-text .required-indicator').exists()).to.equal(false);
    });
    it('should update the form input value when an answer is selected', async () => {
        const formInput = createFormInput();
        const wrapper = await mountFull(ApplicationQuestionRow, { props: { formInput }});

        await wrapper.findAll('input[type="radio"]')[1].setValue(true);

        expect(formInput.value).to.equal(false);
        expect(formInput.isValid).to.equal(true);
    });
});
